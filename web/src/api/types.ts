// Friendly names over the generated contract types (npm run types).
export type {
  Action, ActionKind, Alert, Attack, ApiResponse, CustomActionRequest, InfectResponse, SensorEnrollResponse, SensorSignal, SensorStatus, BlastRadius, Case, CaseDetail, CaseState, Evidence, Finding, SealStatus, Severity, Step,
  VultrInstance, EventActionApplied as ActionApplied, EventActionProposed as ActionProposed,
  EventDnsCaptured as DnsCaptured, EventFindingAdded as FindingAdded, EventSealCheck as SealCheck,
  EventStateChanged as StateChanged, EventStepFinished as StepFinished, EventStepStarted as StepStarted,
  EventTeardownDone as TeardownDone,
} from './types.gen'

export const EVENT_NAMES = [
  'state_changed', 'seal_check', 'step_started', 'step_finished', 'dns_captured',
  'finding_added', 'action_proposed', 'action_applied', 'teardown_done',
] as const
export type EventName = (typeof EVENT_NAMES)[number]

export const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, info: 3 } as const

