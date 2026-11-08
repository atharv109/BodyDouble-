import { useNavigate } from 'react-router'

/** Beat 9's action. Task 4 turns this into the live fake-case hand-off. */
export function TryIt({ label }: { label: string }) {
  const navigate = useNavigate()
  return (
    <div className="mt-8">
      <button type="button" data-testid="try-it" className="btn btn-agent btn-xl" onClick={() => navigate('/console', { viewTransition: true })}>{label}</button>
    </div>
  )
}
