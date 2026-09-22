/** A small receipt assistant. Movement is disabled by the global reduced-motion rule. */
export function CopilotAgent() {
  return <svg className="copilot-agent size-11 shrink-0" viewBox="0 0 64 64" role="img" aria-label="Friendly receipt assistant">
    <path className="copilot-agent-body" d="M17 8h30v45l-5-3-5 3-5-3-5 3-5-3-5 3V8Z" fill="#fafffc" stroke="#205b44" strokeWidth="3" strokeLinejoin="round" />
    <path d="M24 17h16M24 22h13" stroke="#a4d6b6" strokeWidth="2" strokeLinecap="round" />
    <circle cx="26" cy="33" r="2.3" fill="#205b44" />
    <circle cx="38" cy="33" r="2.3" fill="#205b44" />
    <path d="M28 40q4 4 8 0" fill="none" stroke="#205b44" strokeWidth="2.5" strokeLinecap="round" />
    <path className="copilot-agent-wave" d="M46 36q8-10 10-2" fill="none" stroke="#205b44" strokeWidth="3" strokeLinecap="round" />
    <path d="M8 29l2 3 3 2-3 2-2 3-2-3-3-2 3-2z" fill="#e9bf6b" />
  </svg>;
}
