export interface PolymarketIdentity {
  wallet_address: string | null
  funder_address: string | null
  signature_type: number | null
  profile_address: string | null
  profile_name: string | null
  profile_pseudonym: string | null
  profile_image: string | null
  profile_verified: boolean | null
  profile_x_username: string | null
}

export interface PolymarketIdentityDisplay {
  title: string
  imageUrl: string | null
  verified: boolean
  profileAddress: string | null
  walletAddress: string | null
  funderAddress: string | null
  xUsername: string | null
}

const cleanText = (value: string | null | undefined): string | null => {
  const text = value?.trim()
  return text ? text : null
}

const sameAddress = (left: string | null, right: string | null): boolean => {
  return left !== null && right !== null && left.toLowerCase() === right.toLowerCase()
}

export const resolvePolymarketIdentityDisplay = (
  identity: PolymarketIdentity | null | undefined,
): PolymarketIdentityDisplay => {
  const profileName = cleanText(identity?.profile_name)
  const pseudonym = cleanText(identity?.profile_pseudonym)
  const profileAddress = cleanText(identity?.profile_address)
  const walletAddress = cleanText(identity?.wallet_address)
  const funderAddress = cleanText(identity?.funder_address)

  return {
    title: profileName ?? pseudonym ?? 'Polymarket 资料未解析',
    imageUrl: cleanText(identity?.profile_image),
    verified: identity?.profile_verified === true,
    profileAddress,
    walletAddress,
    funderAddress: sameAddress(funderAddress, profileAddress) ? null : funderAddress,
    xUsername: cleanText(identity?.profile_x_username),
  }
}
