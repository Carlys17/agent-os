// Copy with a non-secure-context fallback, mirroring the shared CommandLine
// copy contract (clipboard API, else a hidden-textarea execCommand). Legacy
// sessions used a bare navigator.clipboard call with no fallback, so this is a
// deliberate uplift (recorded as ported(uplift) in the parity matrix) that lets
// the copy work when the page isn't served from a secure context.
export function copyWithFallback(text: string): Promise<void> {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(text)
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  return ok ? Promise.resolve() : Promise.reject(new Error('Copy command failed'))
}
