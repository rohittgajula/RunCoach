import { useState } from 'react'
import { ApiError, apiBlob } from '../../lib/auth'
import { dateTime } from '../../lib/format'
import { errorText } from '../../lib/queries'
import { exportBusy, useExportStatus, useRequestExport } from '../../lib/r13'
import { DownloadIcon } from '../Icons'
import { CardHead } from '../Kit'
import { Skeleton } from '../States'

const size = (b: number | null | undefined) =>
  b == null ? '' : b > 1_000_000 ? `${(b / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1000))} kB`

const HEAD: Record<string, string> = {
  pending: 'Building your export…',
  running: 'Building your export…',
  ready: 'Ready to download',
  failed: 'Export failed',
  expired: 'Link expired',
  downloaded: 'Downloaded',
}

/** "Try again after 14:32" from a 429's retry_after_s. */
function retryText(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null
  const after = (error.detail as { retry_after_s?: number } | null)?.retry_after_s
  if (!after) return 'One export per hour — try again a little later.'
  const at = new Date(Date.now() + after * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return `One export per hour — you can request the next one at ${at}.`
}

/**
 * R13 §15 Me → Account → "Export my data": request a ZIP (one per hour), watch it build,
 * download it through the signed-in session (one-time link, expires after 24 h).
 */
export function ExportSection() {
  const status = useExportStatus()
  const request = useRequestExport()
  const [downloading, setDownloading] = useState(false)
  const [dlError, setDlError] = useState('')
  const job = status.data?.export ?? null
  const building = exportBusy(job) || request.isPending

  const download = async () => {
    if (!job?.download_url) return
    setDownloading(true)
    setDlError('')
    try {
      const blob = await apiBlob(job.download_url)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `runcoach-export-${job.created_at.slice(0, 10)}.zip`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10_000)
    } catch (e) {
      setDlError(
        e instanceof ApiError && e.status === 410
          ? 'This link has already been used or has expired. Request a new export.'
          : errorText(e, 'The download did not start. Try again, or request a new export.'),
      )
    } finally {
      setDownloading(false)
      status.refetch()
    }
  }

  const retry = retryText(request.error)

  return (
    <section className="card stack">
      <CardHead
        title="Export my data"
        sub="Everything RunCoach stores about you as CSV files in one ZIP — runs, laps, daily wellness, habits, cravings, mood, water, meals, weights, plans, strength, pain, reports — plus your settings."
      />
      {status.isPending ? (
        <Skeleton lines={2} />
      ) : status.data === null ? (
        <p className="muted small">Export isn’t available on this server yet.</p>
      ) : (
        <>
          {job && (
            <div className={`export-status is-${job.status}`} role="status" aria-live="polite">
              {building && <span className="export-spinner" aria-hidden="true" />}
              <div className="grow">
                <b>{HEAD[job.status] ?? job.status}</b>
                <span className="muted small block">
                  {job.status === 'ready' && job.expires_at
                    ? `${size(job.size_bytes)}${job.size_bytes ? ' · ' : ''}works once, until ${dateTime(job.expires_at)}`
                    : job.status === 'failed'
                      ? job.error || 'Something went wrong on our side. Try again in a bit.'
                      : job.status === 'expired'
                        ? 'Links last 24 hours. Request a new one.'
                        : job.status === 'downloaded'
                          ? `Saved ${job.finished_at ? dateTime(job.finished_at) : ''}. The file has been deleted from our server.`
                          : 'Usually under a minute. You can leave this page.'}
                </span>
              </div>
            </div>
          )}
          {job?.status === 'ready' && job.download_url && (
            <button type="button" className="btn btn-primary btn-block export-btn" onClick={download} disabled={downloading}>
              <DownloadIcon size={18} /> {downloading ? 'Downloading…' : 'Download ZIP'}
            </button>
          )}
          {dlError && <p className="bad small">{dlError}</p>}
          {retry ? (
            <p className="muted small">{retry}</p>
          ) : (
            request.isError && <p className="bad small">{errorText(request.error, 'Could not start the export.')}</p>
          )}
          {job?.status !== 'ready' && (
            <button type="button" className="btn btn-primary btn-block" onClick={() => request.mutate()} disabled={building}>
              {building ? 'Building…' : job ? 'Request a new export' : 'Request export'}
            </button>
          )}
          <p className="muted small">Private: it downloads through your signed-in session and is deleted after download or 24 hours. One export per hour.</p>
        </>
      )}
    </section>
  )
}
