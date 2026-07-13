import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function IconBase({ children, ...props }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
      {children}
    </svg>
  )
}

export const GaugeIcon = (props: IconProps) => <IconBase {...props}><path d="M4 14a8 8 0 1 1 16 0"/><path d="m12 14 4-4"/><path d="M5 19h14"/></IconBase>
export const KeyIcon = (props: IconProps) => <IconBase {...props}><circle cx="8" cy="15" r="4"/><path d="m11 12 8-8M16 7l2 2M14 9l2 2"/></IconBase>
export const SlidersIcon = (props: IconProps) => <IconBase {...props}><path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h7M15 18h5"/><circle cx="16" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="13" cy="18" r="2"/></IconBase>
export const CopyIcon = (props: IconProps) => <IconBase {...props}><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></IconBase>
export const RefreshIcon = (props: IconProps) => <IconBase {...props}><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 9a7 7 0 0 1 11.6-2L20 12M4 12l2.3 5a7 7 0 0 0 11.6-2"/></IconBase>
export const CheckIcon = (props: IconProps) => <IconBase {...props}><path d="m5 12 4 4L19 6"/></IconBase>
export const BoltIcon = (props: IconProps) => <IconBase {...props}><path d="m13 2-9 12h8l-1 8 9-12h-8z"/></IconBase>
export const ShieldIcon = (props: IconProps) => <IconBase {...props}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10"/><path d="m9 12 2 2 4-4"/></IconBase>
export const ExternalIcon = (props: IconProps) => <IconBase {...props}><path d="M15 4h5v5M13 11l7-7"/><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/></IconBase>
export const CloseIcon = (props: IconProps) => <IconBase {...props}><path d="m6 6 12 12M18 6 6 18"/></IconBase>
export const EyeIcon = (props: IconProps) => <IconBase {...props}><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12"/><circle cx="12" cy="12" r="2.5"/></IconBase>
export const TokenIcon = (props: IconProps) => <IconBase {...props}><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6"/><path d="M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></IconBase>

