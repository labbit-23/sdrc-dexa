import { NextRequest, NextResponse } from 'next/server'
import puppeteer from 'puppeteer'

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get('patient')
  if (!patientId || !/^[\w-]+$/.test(patientId)) {
    return NextResponse.json({ error: 'Missing or invalid ?patient= param' }, { status: 400 })
  }

  const host = req.headers.get('host') ?? 'localhost:3000'
  const proto = process.env.NODE_ENV === 'production' ? 'https' : 'http'
  const mode = req.nextUrl.searchParams.get('mode') === 'fat' ? '?mode=fat' : ''
  const reportUrl = `${proto}://${host}/bmd/render/${patientId}${mode}`

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
        'Content-Disposition': `attachment; filename="${patientId}_dexa_report_dark.pdf"`,
      },
    })
  } finally {
    await browser.close()
  }
}
