/** Logo « Ereuna » : un arbre dont une branche cherche (le rond est le nœud mis en évidence). Sources dans docs/brand/. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <circle cx="20" cy="20" r="20" fill="var(--accent)" />
      <g fill="none" stroke="var(--on-accent)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
        <path d="M20 33V24M20 24L12 17L9 10M20 24L28 15" />
        <circle cx="28" cy="15" r="4.4" fill="var(--accent)" />
      </g>
      <g fill="var(--on-accent)">
        <circle cx="20" cy="33" r="2.4" />
        <circle cx="20" cy="24" r="2.4" />
        <circle cx="12" cy="17" r="2.4" />
        <circle cx="9" cy="10" r="2.2" />
        <circle cx="28" cy="15" r="1.6" />
      </g>
    </svg>
  );
}
