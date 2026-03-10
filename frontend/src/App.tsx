import { Routes, Route } from 'react-router-dom'
import { HomePage } from './pages/HomePage'
import { AlertasPage } from './pages/AlertasPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/alertas" element={<AlertasPage />} />
    </Routes>
  )
}

export default App
