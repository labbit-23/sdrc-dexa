import { NextRequest, NextResponse } from 'next/server'
import { readFileSync } from 'fs'
import { join } from 'path'

const DATA_DIR = process.env.BMD_DATA_DIR ?? '/tmp/sdrc-reports'

export async function GET(
  _req: NextRequest,
  { params }: { params: { patientId: string; filename: string } }
) {
  const { patientId, filename } = params
  if (!/^[\w-]+$/.test(patientId) || !/^[\w.-]+$/.test(filename)) {
    return new NextResponse('Invalid path', { status: 400 })
  }
  const filePath = join(DATA_DIR, patientId, filename)
  try {
    const data = readFileSync(filePath)
    return new NextResponse(data, {
      headers: { 'Content-Type': 'image/png' },
    })
  } catch {
    return new NextResponse('Image not found', { status: 404 })
  }
}
