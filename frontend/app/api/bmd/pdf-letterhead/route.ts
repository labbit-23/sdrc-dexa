import { NextRequest, NextResponse } from 'next/server'
import puppeteer from 'puppeteer'

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get('patient')
  if (!patientId || !/^[\w-]+$/.test(patientId)) {
    return NextResponse.json({ error: 'Missing or invalid ?patient= param' }, { status: 400 })
  }

  const host = req.headers.get('host') ?? 'localhost:3000'
  const proto = process.env.NODE_ENV === 'production' ? 'https' : 'http'
  const mode = req.nextUrl.searchParams.get('mode') === 'fat' ? '&mode=fat' : ''
  // dark=0 (light) + lh=1 (letterhead margins, no logo/footer)
  const reportUrl = `${proto}://${host}/bmd/render/${patientId}?dark=0&lh=1${mode}`

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

    // Margins are defined via @page CSS in letterheadCss (35mm top, 28mm bottom)
    const pdf = await page.pdf({
      format: 'A4',
      printBackground: true,
      margin: { top: 0, bottom: 0, left: 0, right: 0 },
    })

    return new NextResponse(Buffer.from(pdf), {
      headers: {
        'Content-Type': 'application/pdf',
        'Content-Disposition': `attachment; filename="${patientId}_dexa_report_letterhead.pdf"`,
      },
    })
  } finally {
    await browser.close()
  }
}
