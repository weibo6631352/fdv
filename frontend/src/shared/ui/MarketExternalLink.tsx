import type { MouseEventHandler, ReactNode } from 'react'
import { buildPolymarketEventUrl } from '../utils/markets'

interface MarketExternalLinkProps {
  eventSlug?: string | null
  marketSlug?: string | null
  className?: string
  onClick?: MouseEventHandler<HTMLElement>
  children: ReactNode
}

export const MarketExternalLink = ({
  eventSlug,
  marketSlug,
  className,
  onClick,
  children,
}: MarketExternalLinkProps) => {
  const url = buildPolymarketEventUrl(eventSlug, marketSlug)
  if (!url) {
    return (
      <span className={className} onClick={onClick}>
        {children}
      </span>
    )
  }
  return (
    <a href={url} target="_blank" rel="noreferrer" className={className} onClick={onClick}>
      {children}
    </a>
  )
}
