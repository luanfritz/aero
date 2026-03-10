import { Routes, Route } from 'react-router-dom'
import { HomePage } from './pages/HomePage'
import { AlertasPage } from './pages/AlertasPage'
import { AdminAlertasPage } from './pages/AdminAlertasPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/alertas" element={<AlertasPage />} />
      <Route path="/admin/alertas" element={<AdminAlertasPage />} />
    </Routes>
  )
}

export default App
