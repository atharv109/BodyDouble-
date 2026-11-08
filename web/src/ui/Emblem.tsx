/**
 * The brand mark, redrawn as vector: a frame holding the original (ink) and its twin (brass).
 * Parts carry data-part names so the story's peel can move them; the static mark is the rest pose.
 */
export function Emblem({ className, title }: { className?: string; title?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true} overflow="visible">
      <rect data-part="frame" x="6" y="6" width="52" height="52" rx="12" fill="none" stroke="var(--color-agent)" strokeWidth="4.5" />
      <g data-part="original">
        <rect x="14" y="14" width="24" height="25" rx="4.5" fill="var(--color-ink)" />
        <path d="M19.5 21.5h13M19.5 28h13" stroke="var(--color-ground)" strokeWidth="3.2" strokeLinecap="round" />
      </g>
      <g data-part="twin" className="twin-pane">
        <rect x="27" y="28" width="23" height="23" rx="4.5" fill="var(--color-agent)" stroke="var(--color-ground)" strokeWidth="3.5" paintOrder="stroke" />
        <path d="M32.5 36h12M32.5 42.5h12" stroke="var(--color-ground)" strokeWidth="3.2" strokeLinecap="round" />
      </g>
    </svg>
  )
}
