import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AppProvider, useApp } from './context/AppContext';
import AppShell from './components/AppShell';
import { LOGIN_PATH } from './components/navConfig';

import Landing from './pages/candidate/Landing';
import AuthPage from './pages/auth/AuthPage';
import CandidateDashboard from './pages/candidate/Dashboard';
import JobListings from './pages/candidate/JobListings';
import Apply from './pages/candidate/Apply';
import Applications from './pages/candidate/Applications';
import Assessments from './pages/candidate/Assessments';
import Assessment from './pages/candidate/Assessment';
import CandidateInterviews from './pages/candidate/Interviews';
import CandidateOffers from './pages/candidate/Offers';
import OfferView from './pages/candidate/OfferView';
import CandidateProfile from './pages/candidate/Profile';
import AtsChecker from './pages/candidate/AtsChecker';
import Refer from './pages/candidate/Refer';
import MockInterview from './pages/candidate/MockInterview';
import MockAssessment from './pages/candidate/MockAssessment';
import ContactUs from './pages/candidate/ContactUs';

import HrDashboard from './pages/hr/Dashboard';
import HrJobs from './pages/hr/Jobs';
import PostJob from './pages/hr/PostJob';
import HrApplications from './pages/hr/Applications';
import HrCandidates from './pages/hr/Candidates';
import CandidateDetail from './pages/hr/CandidateDetail';
import HrAssessments from './pages/hr/Assessments';
import HrInterviews from './pages/hr/Interviews';
import HrOffers from './pages/hr/Offers';
import Company from './pages/hr/Company';
import Verification from './pages/hr/Verification';
import Credits from './pages/hr/Credits';
import BuyCredits from './pages/hr/BuyCredits';
import Billing from './pages/hr/Billing';

import Settings from './pages/shared/Settings';
import AdminLogin from './pages/admin/Login';
import { AdminOverview, AdminVerifications, AdminUsers, AdminJobs, AdminSupport, AdminEmails, AdminSystem } from './pages/admin/Console';
import Support from './pages/shared/Support';


function Protected({ role, children, wide }) {
  const { user } = useApp();
  const location = useLocation();
  if (!user?.token || user.role !== role) {
    return <Navigate to={LOGIN_PATH[role]} replace state={{ from: location.pathname + location.search }} />;
  }
  return <AppShell role={role} wide={wide}>{children}</AppShell>;
}

const C = (el, wide) => <Protected role="candidate" wide={wide}>{el}</Protected>;
const H = (el, wide) => <Protected role="hr" wide={wide}>{el}</Protected>;
const A = (el, wide) => <Protected role="admin" wide={wide}>{el}</Protected>;

export default function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<AuthPage role="talent" mode="in" />} />
          <Route path="/signup" element={<AuthPage role="talent" mode="up" />} />
          <Route path="/hr/login" element={<AuthPage role="ent" mode="in" />} />
          <Route path="/hr/signup" element={<AuthPage role="ent" mode="up" />} />

          <Route path="/dashboard" element={C(<CandidateDashboard />)} />
          <Route path="/jobs" element={C(<JobListings />)} />
          <Route path="/apply/:jobId" element={C(<Apply />)} />
          <Route path="/applications" element={C(<Applications />)} />
          <Route path="/assessments" element={C(<Assessments />)} />
          <Route path="/assessment" element={C(<Assessment />, true)} />
          <Route path="/interviews" element={C(<CandidateInterviews />)} />
          <Route path="/offers" element={C(<CandidateOffers />)} />
          <Route path="/offers/:id" element={C(<OfferView />)} />
          <Route path="/profile" element={C(<CandidateProfile />)} />
          <Route path="/ats" element={C(<AtsChecker />)} />
          <Route path="/refer" element={C(<Refer />)} />
          <Route path="/mock-interview" element={C(<MockInterview />, true)} />
          <Route path="/mock-interview/:id" element={C(<MockInterview />, true)} />
          <Route path="/mock-assessment" element={C(<MockAssessment />, true)} />
          <Route path="/mock-assessment/:id" element={C(<MockAssessment />, true)} />
          <Route path="/contact" element={C(<ContactUs />)} />
          <Route path="/support" element={C(<Support />)} />
          <Route path="/settings" element={C(<Settings />)} />

          <Route path="/hr" element={H(<HrDashboard />)} />
          <Route path="/hr/jobs" element={H(<HrJobs />)} />
          <Route path="/hr/post-job" element={H(<PostJob />)} />
          <Route path="/hr/applications" element={H(<HrApplications />, true)} />
          <Route path="/hr/candidates" element={H(<HrCandidates />, true)} />
          <Route path="/hr/candidate/:id" element={H(<CandidateDetail />)} />
          <Route path="/hr/assessments" element={H(<HrAssessments />, true)} />
          <Route path="/hr/interviews" element={H(<HrInterviews />)} />
          <Route path="/hr/schedule" element={<Navigate to="/hr/interviews" replace />} />
          <Route path="/hr/offers" element={H(<HrOffers />, true)} />
          <Route path="/hr/company" element={H(<Company />)} />
          <Route path="/hr/verification" element={H(<Verification />)} />
          <Route path="/hr/credits" element={H(<Credits />)} />
          <Route path="/hr/credits/buy" element={H(<BuyCredits />, true)} />
          <Route path="/hr/billing" element={H(<Billing />)} />
          <Route path="/hr/settings" element={H(<Settings />)} />
          <Route path="/hr/support" element={H(<Support />)} />


          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin" element={A(<AdminOverview />)} />
          <Route path="/admin/verifications" element={A(<AdminVerifications />)} />
          <Route path="/admin/users" element={A(<AdminUsers />, true)} />
          <Route path="/admin/jobs" element={A(<AdminJobs />)} />
          <Route path="/admin/support" element={A(<AdminSupport />)} />
          <Route path="/admin/emails" element={A(<AdminEmails />, true)} />
          <Route path="/admin/system" element={A(<AdminSystem />)} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
