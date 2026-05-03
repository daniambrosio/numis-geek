import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Profile from './pages/Profile'
import AdminUsers from './pages/admin/Users'
import AdminAudit from './pages/admin/Audit'
import AdminAccounts from './pages/admin/Accounts'
import Assets from './pages/admin/Assets'
import SysAdminFinancialInstitutions from './pages/sysadmin/FinancialInstitutions'
import SysAdminAssets from './pages/sysadmin/Assets'
import { applyTheme, getTheme } from './lib/theme'
import { getToken } from './lib/api'

// Apply saved theme before first render
applyTheme(getTheme())

function PrivateRoute({ children }: { children: React.ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={<PrivateRoute><Dashboard /></PrivateRoute>} />
        <Route path="/profile" element={<PrivateRoute><Profile /></PrivateRoute>} />
        <Route path="/accounts" element={<PrivateRoute><AdminAccounts /></PrivateRoute>} />
        <Route path="/assets" element={<PrivateRoute><Assets /></PrivateRoute>} />
        <Route path="/admin/users" element={<PrivateRoute><AdminUsers /></PrivateRoute>} />
        <Route path="/admin/audit" element={<PrivateRoute><AdminAudit /></PrivateRoute>} />
        <Route path="/sysadmin/financial-institutions" element={<PrivateRoute><SysAdminFinancialInstitutions /></PrivateRoute>} />
        <Route path="/sysadmin/assets" element={<PrivateRoute><SysAdminAssets /></PrivateRoute>} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
