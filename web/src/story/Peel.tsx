/**
 * The signature: the emblem as a stage. At rest it is the brand mark (the twin overlaps the original
 * inside one brass frame). On load the twin peels off: the original stays behind glass
 * (grey frame, "untouched"), the snapshot line runs across, and the twin's own brass frame draws shut
 * ("sealed"). Geometry is in SVG units; usePeel() in motion.ts animates the data-peel parts.
 */
export function Peel() {
  return (
    <div className="peel-box">
    <svg className="peel" viewBox="0 0 150 66" role="img"
      aria-label="The Body Double mark coming apart: the original server stays in a grey frame marked untouched, and its twin moves into its own sealed brass frame.">
      <defs>
        <clipPath id="peel-twin-clip"><rect x="70" y="32" width="23" height="23" rx="4.5" /></clipPath>
      </defs>
      {/* glass around the original: starts as the brand frame around both, ends hugging the original */}
      <rect data-peel="glass" x="49" y="10" width="52" height="52" rx="12" fill="none" stroke="var(--color-agent)" strokeWidth="4.5" />
      <g data-peel="snapshot" opacity="0">
        <path d="M63.5 30.5H90" stroke="var(--color-agent)" strokeWidth="0.6" strokeDasharray="1.6 1.6" />
      </g>
      <g data-peel="original">
        <rect x="57" y="18" width="24" height="25" rx="4.5" fill="var(--color-ink)" />
        <path d="M62.5 25.5h13M62.5 32h13" stroke="var(--color-ground)" strokeWidth="3.2" strokeLinecap="round" />
      </g>
      <rect data-peel="seal" x="92" y="11.5" width="38" height="38" rx="8" fill="none" stroke="var(--color-agent)" strokeWidth="2.4" pathLength="1" strokeDasharray="1 1" strokeDashoffset="1" opacity="0" />
      <g data-peel="twin">
        <rect x="70" y="32" width="23" height="23" rx="4.5" fill="var(--color-agent)" stroke="var(--color-ground)" strokeWidth="3.5" paintOrder="stroke" />
        <path d="M75.5 40h12M75.5 46.5h12" stroke="var(--color-ground)" strokeWidth="3.2" strokeLinecap="round" />
        {/* the agent reading the copy: a scan line that only ever passes over the twin */}
        <g clipPath="url(#peel-twin-clip)"><rect data-peel="scan" x="70" y="31" width="23" height="1.1" fill="var(--color-ink)" opacity="0" /></g>
      </g>
    </svg>
    {/* labels are HTML laid over the drawing (positions in SVG units / viewBox), so their contrast is measurable;
        the svg's aria-label already says all of this */}
    <div className="peel-labels" aria-hidden="true">
      <span data-peel="snapshot-label" className="peel-label" style={{ left: at(76.75, 150), top: at(28, 66), opacity: 0 }}>snapshot</span>
      <div data-peel="labels" style={{ opacity: 0 }}>
        <span className="peel-label" style={{ left: at(42, 150), top: at(59, 66) }}>production · untouched</span>
        <span className="peel-label peel-label--agent" style={{ left: at(111, 150), top: at(59, 66) }}>twin · sealed</span>
      </div>
    </div>
    </div>
  )
}

const at = (v: number, of: number) => `${(v / of) * 100}%`

/** End pose of the peel, shared by the scroll timeline and the reduced-motion still. */
export const PEEL_END = {
  glass: { x: 23, y: 11.5, width: 38, height: 38, rx: 8, 'stroke-width': 2.4 },
  original: { x: -27, y: 0 },
  twin: { x: 29.5, y: -13 },
}
