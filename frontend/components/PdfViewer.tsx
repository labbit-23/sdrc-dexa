'use client'

interface Props {
  url: string
}

export default function PdfViewer({ url }: Props) {
  return (
    <div className="w-full">
      {/* iframe embed works for Supabase public storage URLs */}
      <iframe
        src={url}
        className="w-full rounded-lg border border-gray-200"
        style={{ height: '80vh', minHeight: 600 }}
        title="BMD Report PDF"
      />
      <p className="text-xs text-gray-400 mt-2 text-center">
        Can&apos;t see the PDF?{' '}
        <a href={url} target="_blank" rel="noopener noreferrer"
           className="text-[#0D7377] underline">
          Open in new tab
        </a>
      </p>
    </div>
  )
}
