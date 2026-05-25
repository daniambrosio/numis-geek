import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Profile from './pages/Profile'
import AdminUsers from './pages/admin/Users'
import AdminAudit from './pages/admin/Audit'
import AdminAccounts from './pages/admin/Accounts'
import Assets from './pages/admin/Assets'
import AssetDetail from './pages/AssetDetail'
import AssetMovements from './pages/AssetMovements'
import DecisionSupport from './pages/DecisionSupport'
import Portfolio from './pages/Portfolio'
import Distributions from './pages/Distributions'
import Snapshots from './pages/Snapshots'
import SnapshotDetail from './pages/SnapshotDetail'
import SysAdminFinancialInstitutions from './pages/sysadmin/FinancialInstitutions'
import SysAdminAssets from './pages/sysadmin/Assets'
import SysAdminIntegrations from './pages/sysadmin/Integrations'
import SysAdminPTAX from './pages/sysadmin/PTAX'
import ComingSoon from './components/ComingSoon'
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

        {/* Investimentos */}
        <Route path="/portfolio" element={<PrivateRoute><Portfolio /></PrivateRoute>} />
        <Route path="/decision-support" element={<PrivateRoute><DecisionSupport /></PrivateRoute>} />
        <Route path="/assets" element={<PrivateRoute><Assets /></PrivateRoute>} />
        <Route path="/assets/:id" element={<PrivateRoute><AssetDetail /></PrivateRoute>} />
        <Route path="/asset-movements" element={<PrivateRoute><AssetMovements /></PrivateRoute>} />
        <Route path="/distributions" element={<PrivateRoute><Distributions /></PrivateRoute>} />
        <Route path="/snapshots" element={<PrivateRoute><Snapshots /></PrivateRoute>} />
        <Route path="/snapshots/:ym" element={<PrivateRoute><SnapshotDetail /></PrivateRoute>} />

        {/* Caixa & Cartões */}
        <Route path="/transactions" element={<PrivateRoute><ComingSoon title="Movimentações" hint="Transações de contas e cartões. Depende da entidade Transaction (Spec 23)." /></PrivateRoute>} />
        <Route path="/credit-cards" element={<PrivateRoute><ComingSoon title="Cartões" hint="Cartões de crédito como entidade própria. Depende do Spec 23." /></PrivateRoute>} />
        <Route path="/invoices" element={<PrivateRoute><ComingSoon title="Faturas" hint="Fechamento de cartão por período. Depende do Spec 23." /></PrivateRoute>} />
        <Route path="/budget" element={<PrivateRoute><ComingSoon title="Orçamento" hint="Categorias × meses, com targets. Depende dos Specs 19 + 23." /></PrivateRoute>} />

        {/* Estrutura */}
        <Route path="/financial-institutions" element={<PrivateRoute><ComingSoon title="Instituições" hint="FI Hub com contas, cartões e ativos agregados. Chega no Spec 22." /></PrivateRoute>} />
        <Route path="/accounts" element={<PrivateRoute><AdminAccounts /></PrivateRoute>} />

        {/* Legacy PT routes — redirect to EN equivalents (mantido por 1 ciclo) */}
        <Route path="/patrimonio" element={<Navigate to="/portfolio" replace />} />
        <Route path="/onde-investir" element={<Navigate to="/decision-support" replace />} />
        <Route path="/lancamentos" element={<Navigate to="/asset-movements" replace />} />
        <Route path="/proventos" element={<Navigate to="/distributions" replace />} />
        <Route path="/movimentacoes" element={<Navigate to="/transactions" replace />} />
        <Route path="/cartoes" element={<Navigate to="/credit-cards" replace />} />
        <Route path="/faturas" element={<Navigate to="/invoices" replace />} />
        <Route path="/orcamento" element={<Navigate to="/budget" replace />} />
        <Route path="/instituicoes" element={<Navigate to="/financial-institutions" replace />} />

        {/* Admin */}
        <Route path="/admin/users" element={<PrivateRoute><AdminUsers /></PrivateRoute>} />
        <Route path="/admin/audit" element={<PrivateRoute><AdminAudit /></PrivateRoute>} />

        {/* Sistema */}
        <Route path="/sysadmin/financial-institutions" element={<PrivateRoute><SysAdminFinancialInstitutions /></PrivateRoute>} />
        <Route path="/sysadmin/assets" element={<PrivateRoute><SysAdminAssets /></PrivateRoute>} />
        <Route path="/sysadmin/integrations" element={<PrivateRoute><SysAdminIntegrations /></PrivateRoute>} />
        <Route path="/sysadmin/ptax" element={<PrivateRoute><SysAdminPTAX /></PrivateRoute>} />

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
