import { createContext, useContext } from 'react'

/** Dashboard pages that have a tab; their names can be changed by an admin (✏️ next to the tabs). */
export type PageKey = 'home' | 'flowaccount' | 'account' | 'personal' | 'company' | 'members'
export type PageNames = Record<PageKey, string>

/** The names until the server's arrive (the same defaults as backend/app/page_names.py). */
export const DEFAULT_NAMES: PageNames = {
  home: '🏠 บ้าน',
  flowaccount: '📄 FlowAccount',
  account: '💰 Account ภาษี',
  personal: '💳 การเงินส่วนตัว',
  company: '🏢 การเงินบริษัท',
  members: '👥 สมาชิก',
}

export const PageNamesContext = createContext<PageNames>(DEFAULT_NAMES)

export function usePageNames(): PageNames {
  return useContext(PageNamesContext)
}
