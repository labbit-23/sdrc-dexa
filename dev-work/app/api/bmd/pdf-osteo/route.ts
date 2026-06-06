import { NextRequest, NextResponse } from 'next/server'
import { readFileSync } from 'fs'
import { join } from 'path'
import puppeteer from 'puppeteer'

const DATA_DIR = process.env.BMD_DATA_DIR ?? '/tmp/sdrc-reports'

function safe(s: string) { return s.replace(/[^a-zA-Z0-9]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '') }

function buildFilename(patientId: string, lh: boolean): string {
  try {
    const raw = JSON.parse(readFileSync(join(DATA_DIR, `${patientId}_raw_osteo.json`), 'utf-8'))
    const snap = raw?.mdb_snapshot
    const patRow = Object.values(snap?.patients ?? {})[0] as any
    const examRow = (snap?.exams ?? [])[0] as any
    const name = [safe(patRow?.last_name ?? ''), safe(patRow?.first_name ?? '')].filter(Boolean).join('_') || safe(patientId)
    const date = (examRow?._acq_dt ?? '').slice(0, 10) || new Date().toISOString().slice(0, 10)
    return `${name}_Bone_Density_${date}${lh ? '_Letterhead' : ''}.pdf`
  } catch {
    return `${safe(patientId)}_Bone_Density${lh ? '_Letterhead' : ''}.pdf`
  }
}

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get('patient')
  if (!patientId || !/^[\w-]+$/.test(patientId)) {
    return NextResponse.json({ error: 'Missing or invalid ?patient= param' }, { status: 400 })
  }

  const host = req.headers.get('host') ?? 'localhost:3000'
  const proto = process.env.NODE_ENV === 'production' ? 'https' : 'http'
  const lh = req.nextUrl.searchParams.get('lh') === '1'
  const reportUrl = `${proto}://${host}/bmd/render/osteo/${patientId}${lh ? '?lh=1' : ''}`

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  })

  try {
    const page = await browser.newPage()
    await page.goto(reportUrl, { waitUntil: 'networkidle0', timeout: 30_000 })

    await page.evaluate(() =>
      Promise.all(
        Array.from(document.images).map(img =>
          img.complete ? Promise.resolve() : new Promise(r => { img.onload = r; img.onerror = r })
        )
      )
    )

    const pdf = await page.pdf({
      format: 'A4',
      printBackground: true,
      margin: { top: 0, bottom: 0, left: 0, right: 0 },
    })

    return new NextResponse(Buffer.from(pdf), {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="${buildFilename(patientId, lh)}"`,
      },
    })
  } finally {
    await browser.close()
  }
}
