import { NextRequest, NextResponse } from 'next/server'
import { readFileSync } from 'fs'
import { join } from 'path'
import { computeOsteoData } from '../../../../../lib/osteo-compute'
import { generateOsteoHtml } from '../../../../../lib/osteo-html-template'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const DATA_DIR = process.env.BMD_DATA_DIR ?? '/tmp/sdrc-reports'

export async function GET(
  req: NextRequest,
  { params }: { params: { patientId: string } }
) {
  const { patientId } = params
  if (!patientId || !/^[\w-]+$/.test(patientId)) {
    return new NextResponse('Invalid patient ID', { status: 400 })
  }

  const filePath = join(DATA_DIR, `${patientId}_raw_osteo.json`)
  let raw: unknown
  try {
    raw = JSON.parse(readFileSync(filePath, 'utf-8'))
  } catch {
    return new NextResponse(`Osteo data not found for ${patientId}`, { status: 404 })
  }

  const host = req.headers.get('host') ?? 'localhost:3001'
  const proto = process.env.NODE_ENV === 'production' ? 'https' : 'http'
  const imageBaseUrl = `${proto}://${host}/api/bmd/image/${patientId}`

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const data = computeOsteoData(raw as any, patientId, imageBaseUrl)

  const dark       = req.nextUrl.searchParams.get('dark') === '1'   // default light
  const letterhead = req.nextUrl.searchParams.get('lh') === '1'
  const html = generateOsteoHtml(data, dark, letterhead)

  return new NextResponse(html, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' },
  })
}
