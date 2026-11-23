import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { StationApp } from './StationApp.tsx'

// Отдельная точка входа: окно стенда не должно тянуть стили планшета и админки.
const root = document.getElementById('root')
if (!root) throw new Error('#root not found')

createRoot(root).render(
  <StrictMode>
    <StationApp />
  </StrictMode>,
)
