/** Original evening mark: one horizon, two stops. Decorative beside the wordmark. */
export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 64 64" aria-hidden="true">
      <rect
        x="2"
        y="2"
        width="60"
        height="60"
        rx="18"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <path d="M16 42c7.5-16 24.5-16 32 0" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <circle cx="26" cy="36" r="2.4" fill="currentColor" />
      <circle cx="40" cy="30" r="2.4" fill="var(--brass)" />
    </svg>
  );
}
