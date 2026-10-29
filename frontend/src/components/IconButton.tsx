import type { ButtonHTMLAttributes } from 'react'
import type { IconDefinition } from '@fortawesome/fontawesome-svg-core'
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  icon: IconDefinition
  label: string
  variant?: 'default' | 'danger' | 'secondary'
  spinning?: boolean
}

export function IconButton({
  icon,
  label,
  variant = 'default',
  spinning = false,
  className = '',
  type = 'button',
  ...props
}: Props) {
  return (
    <button
      {...props}
      type={type}
      aria-label={label}
      title={label}
      className={`icon-button icon-button--${variant} ${className}`.trim()}
    >
      <FontAwesomeIcon icon={icon} spin={spinning} aria-hidden="true" />
    </button>
  )
}
