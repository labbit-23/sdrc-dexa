/**
 * POST /api/regenerate
 * Body: { scan_handle: string }
 *
 * Calls the worker pipeline on-demand by POSTing to a small HTTP endpoint
 * that the worker exposes locally (optional), OR queues a regeneration job.
 *
 * Simple implementation: marks the scan_handle as unprocessed in a Supabase
 * table so the next watcher cycle picks it up. For immediate re-generation,
 * call the worker's local HTTP API if available.
 */
import { NextRequest, NextResponse } from 'next/server'
import { createClient } from '@supabase/supabase-js'

const sb = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_KEY!,
  { global: { fetch: (url, options = {}) => fetch(url, { ...options, signal: AbortSignal.timeout(15000) }) } },
)

export async function POST(req: NextRequest) {
  try {
    const { scan_handle } = await req.json()
    if (!scan_handle) {
      return NextResponse.json({ ok: false, error: 'scan_handle required' }, { status: 400 })
    }

    // Try to call the worker's local HTTP API (if running)
    const workerUrl = process.env.WORKER_HTTP_URL
    if (workerUrl) {
      try {
        const r = await fetch(`${workerUrl}/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ scan_handle }),
          signal: AbortSignal.timeout(10_000),
        })
        if (r.ok) {
          return NextResponse.json({ ok: true, via: 'worker' })
        }
      } catch {
        // Worker not reachable — fall through to queuing
      }
    }

    // Fallback: delete existing report so watcher re-generates on next poll
    const scanRes = await sb.from('scans').select('id').eq('scan_handle', scan_handle).single()
    if (scanRes.data) {
      await sb.from('reports').delete().eq('scan_id', scanRes.data.id)
    }

    return NextResponse.json({ ok: true, via: 'queue' })
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e) }, { status: 500 })
  }
}
