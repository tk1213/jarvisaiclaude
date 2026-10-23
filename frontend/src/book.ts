import { createContext, useContext } from 'react'
import type { Book } from './api'

/** Which money page a component belongs to: 💳 personal or 🏢 company (same screens, separate data). */
export const BookContext = createContext<Book>('personal')

export function useBook(): Book {
  return useContext(BookContext)
}
