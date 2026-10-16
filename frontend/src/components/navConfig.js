import {
  LayoutDashboard, Search, FileText, ClipboardList, CalendarClock, Award, User, ScanSearch, Gift, Mail,
  LifeBuoy, Settings, Briefcase, Users, UserCheck, Inbox, ServerCog, Building2, ShieldCheck, CreditCard,
  ShoppingCart, Wallet, Mic, ClipboardCheck,
} from 'lucide-react';

export const NAV = {
  candidate: [
    { title: null, items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/jobs', label: 'Jobs', icon: Search },
      { to: '/applications', label: 'My Applications', icon: FileText },
      { to: '/assessments', label: 'Assessments', icon: ClipboardList },
      { to: '/interviews', label: 'Interviews', icon: CalendarClock },
      { to: '/offers', label: 'Offers', icon: Award },
    ] },
    { title: 'Practice', items: [
      { to: '/mock-interview', label: 'Mock Interview', icon: Mic },
      { to: '/mock-assessment', label: 'Mock Assessment', icon: ClipboardCheck },
    ] },
    { title: 'Career tools', items: [
      { to: '/profile', label: 'Profile', icon: User },
      { to: '/ats', label: 'Resume ATS Checker', icon: ScanSearch },
      { to: '/refer', label: 'Refer & Earn', icon: Gift },
    ] },
    { title: 'Help', items: [
      { to: '/contact', label: 'Contact Us', icon: Mail },
      { to: '/support', label: 'Support', icon: LifeBuoy },
      { to: '/settings', label: 'Settings', icon: Settings },
    ] },
  ],
  hr: [
    { title: null, items: [
      { to: '/hr', label: 'Dashboard', icon: LayoutDashboard, end: true },
      { to: '/hr/jobs', label: 'Jobs', icon: Briefcase },
      { to: '/hr/applications', label: 'Applications', icon: FileText },
      { to: '/hr/candidates', label: 'Candidates', icon: Users },
      { to: '/hr/assessments', label: 'Assessments', icon: ClipboardList },
      { to: '/hr/interviews', label: 'Interviews', icon: CalendarClock },
      { to: '/hr/offers', label: 'Offer Letters', icon: Award },
    ] },
    { title: 'Company', items: [
      { to: '/hr/company', label: 'Company Profile', icon: Building2 },
      { to: '/hr/verification', label: 'Verification', icon: ShieldCheck },
    ] },
    { title: 'Account & billing', items: [
      { to: '/hr/credits', label: 'Credits & Usage', icon: CreditCard, end: true },
      { to: '/hr/credits/buy', label: 'Buy Credits', icon: ShoppingCart },
      { to: '/hr/billing', label: 'Billing', icon: Wallet },
    ] },
    { title: 'Preferences', items: [
      { to: '/hr/settings', label: 'Settings', icon: Settings },
      { to: '/hr/support', label: 'Support', icon: LifeBuoy },
    ] },
  ],
  admin: [
    { title: null, items: [
      { to: '/admin', label: 'Overview', icon: LayoutDashboard, end: true },
      { to: '/admin/verifications', label: 'Verifications', icon: UserCheck },
      { to: '/admin/users', label: 'Users & Credits', icon: Users },
      { to: '/admin/jobs', label: 'Jobs', icon: Briefcase },
      { to: '/admin/support', label: 'Support Tickets', icon: Inbox },
      { to: '/admin/emails', label: 'Email Log', icon: Mail },
      { to: '/admin/system', label: 'System', icon: ServerCog },
    ] },
  ],
};

export const HOME = { candidate: '/dashboard', hr: '/hr', admin: '/admin' };
export const PROFILE_PATH = { candidate: '/profile', hr: '/hr/company', admin: '/admin/system' };
export const SETTINGS_PATH = { candidate: '/settings', hr: '/hr/settings', admin: '/admin/system' };
export const LOGIN_PATH = { candidate: '/login', hr: '/hr/login', admin: '/admin/login' };
