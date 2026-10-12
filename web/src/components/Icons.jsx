// Inline icons: no icon font or third-party request (the CSP is 'self' only).
// Each takes className for size and colour; strokes use currentColor.

function Icon({ className = "size-5", children, ...rest }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className} {...rest}>
      {children}
    </svg>
  );
}

export const ArrowUp = (p) => <Icon {...p}><path d="M12 19V5M5 12l7-7 7 7" /></Icon>;

export const Stop = (p) => <Icon {...p}><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none" /></Icon>;

export const Plus = (p) => <Icon {...p}><path d="M12 5v14M5 12h14" /></Icon>;

export const Menu = (p) => <Icon {...p}><path d="M4 6h16M4 12h16M4 18h16" /></Icon>;

export const Close = (p) => <Icon {...p}><path d="M6 6l12 12M18 6L6 18" /></Icon>;

export const Chat = (p) => <Icon {...p}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></Icon>;

export const Info = (p) => <Icon {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></Icon>;

export const Link = (p) => <Icon {...p}><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></Icon>;

export const Spinner = ({ className = "size-4" }) => (
  <svg viewBox="0 0 24 24" aria-hidden="true" className={`animate-spin ${className}`}>
    <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
);

/** The app mark: a speech bubble with a check, in the accent blue. */
export const Mark = ({ className = "size-7" }) => (
  <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
    <rect width="32" height="32" rx="8" fill="var(--accent-strong)" />
    <path d="M10 16.5l4 4 8-9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
