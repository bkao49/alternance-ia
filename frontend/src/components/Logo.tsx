/** Logo provisoire « Piste » (un tracé qui monte vers un point) ; les autres pistes sont dans la maquette I. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <circle cx="20" cy="20" r="20" fill="var(--accent)" />
      <path
        d="M10 27 C16 27 15 15 21 15 S27 13 30 11"
        fill="none"
        stroke="var(--on-accent)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="30" cy="11" r="2.9" fill="var(--on-accent)" />
    </svg>
  );
}
