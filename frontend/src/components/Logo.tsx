export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="0.5" y="0.5" width="31" height="31" rx="9" fill="#0B0D0C" stroke="rgba(255,255,255,0.14)" />
      <path d="M9.5 11.5h13M16 11.5V23" stroke="#F2F0EA" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="16" cy="11.5" r="3.1" fill="#34D399" />
    </svg>
  );
}
