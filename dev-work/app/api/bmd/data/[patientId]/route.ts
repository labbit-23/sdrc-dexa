import { NextRequest, NextResponse } from 'next/server'
import { readFileSync } from 'fs'
import { join } from 'path'

// Local data directory — overridable via BMD_DATA_DIR env var
// Falls back to /tmp/sdrc-reports/{patientId}_raw_data.json
const DATA_DIR = process.env.BMD_DATA_DIR ?? '/tmp/sdrc-reports'

export async function GET(
  _req: NextRequest,
  { params }: { params: { patientId: string } }
) {
  const { patientId } = params
  if (!patientId || !/^[\w-]+$/.test(patientId)) {
    return NextResponse.json({ error: 'Invalid patient ID' }, { status: 400 })
  }

  const filePath = join(DATA_DIR, `${patientId}_raw_data.json`)
  try {
    const raw = readFileSync(filePath, 'utf-8')
    return new NextResponse(raw, {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch {
    return NextResponse.json({ error: `Data not found for ${patientId}` }, { status: 404 })
  }
}
