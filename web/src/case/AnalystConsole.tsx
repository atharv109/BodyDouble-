import { useMemo, useState, type KeyboardEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { AnalystRun, CaseState, ToolName } from '../api/types'

const TOOLS: { value: ToolName; label: string }[] = [
  ['os_facts', 'OS facts'], ['persistence_scan', 'Persistence scan'], ['auth_scan', 'Authentication scan'],
  ['recent_files', 'Recent files'], ['binary_integrity', 'Binary integrity'], ['listener_config', 'Listener config'],
  ['extract', 'Extract file'], ['detonate', 'Detonate file'], ['custom_script', 'Custom Python'],
].map(([value, label]) => ({ value: value as ToolName, label }))
const PATH_TOOLS = new Set<ToolName>(['extract', 'detonate'])
const ALLOWED = new Set<CaseState>(['sealed', 'investigating', 'reported', 'contained'])

export function AnalystConsole({ caseId, state }: { caseId: string; state: CaseState | null }) {
  const [tool, setTool] = useState<ToolName>('os_facts')
  const [path, setPath] = useState('/mnt/evidence/')
  const [code, setCode] = useState('from pathlib import Path\nprint(Path("/mnt/evidence/etc/os-release").read_text())')
  const [runs, setRuns] = useState<AnalystRun[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const enabled = !!state && ALLOWED.has(state)
  const args = useMemo(() => tool === 'custom_script' ? { code } : PATH_TOOLS.has(tool) ? { path } : {}, [tool, code, path])
  const ready = enabled && !busy && (tool !== 'custom_script' || !!code.trim()) && (!PATH_TOOLS.has(tool) || !!path.trim())

  async function run() {
    if (!ready) return
    setBusy(true); setError(null)
    try {
      const completed = await api.analystRun(caseId, tool, args)
      setRuns((xs) => [completed, ...xs])
    }
    catch (e) { setError(e instanceof ApiError ? e.message : String((e as Error).message ?? e)) }
    finally { setBusy(false) }
  }
  const keyRun = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); void run() }
  }

  return (
    <section className="analyst" data-testid="analyst-console" aria-labelledby="analyst-h">
      <header className="analyst-head">
        <div><p className="label">Human workspace</p><h2 id="analyst-h">Analyst Console</h2></div>
        <p className="analyst-boundary"><strong>Read-only cloned disk.</strong> No network. Runs stay inside the case twin and never touch production.</p>
      </header>
      <div className="analyst-workbench">
        <form className="analyst-form" onSubmit={(e) => { e.preventDefault(); void run() }}>
          <label htmlFor="analyst-tool">Forensic tool</label>
          <select id="analyst-tool" value={tool} onChange={(e) => setTool(e.target.value as ToolName)}>{TOOLS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}</select>
          {PATH_TOOLS.has(tool) && <><label htmlFor="analyst-path">Path on cloned disk</label><input id="analyst-path" value={path} onChange={(e) => setPath(e.target.value)} /></>}
          {tool === 'custom_script' && <><label htmlFor="analyst-code">Sandboxed Python</label><textarea id="analyst-code" value={code} onChange={(e) => setCode(e.target.value)} onKeyDown={keyRun} spellCheck={false} rows={9} /><p className="text-muted text-xs">Ctrl/⌘ + Enter to run · standard library only · output limits enforced by the sandbox</p></>}
          <button className="btn btn-agent analyst-run" type="submit" disabled={!ready}>{busy ? 'Running in sandbox…' : 'Run tool'}</button>
          {!enabled && <p className="text-muted text-sm">Tools are unavailable while this case is {state ?? 'loading'}.</p>}
          {error && <p role="alert" className="analyst-error">{error}</p>}
        </form>
        <div className="analyst-history" aria-live="polite" aria-busy={busy}>
          <div className="analyst-history-head"><h3>Command history</h3><span className="font-mono text-xs text-muted">{runs.length} human {runs.length === 1 ? 'run' : 'runs'}</span></div>
          {runs.length === 0 ? <p className="analyst-empty">Choose a forensic tool. Its real command and result will appear here.</p> : runs.map(({ step, result }) => (
            <article key={step.id} className="analyst-record" data-testid="analyst-run">
              <div className="analyst-record-meta"><strong>{step.tool}</strong><span>exit {result.exit_code} · {result.duration_ms} ms</span></div>
              <pre><code>$ {result.code}</code></pre>
              {result.stdout && <pre aria-label="Standard output">{result.stdout}</pre>}
              {result.stderr && <pre className="text-finding" aria-label="Standard error">{result.stderr}</pre>}
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
