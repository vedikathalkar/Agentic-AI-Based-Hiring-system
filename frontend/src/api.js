export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// Turn FastAPI error bodies ({detail: "..."} or 422 [{loc, msg}]) into a readable message.
function errorMessage(status, text) {
  try {
    const body = JSON.parse(text);
    const { detail } = body;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => {
        const field = (d.loc || []).filter((x) => x !== 'body').join('.');
        const msg = String(d.msg || '').replace(/^Value error, /, '');
        return field ? `${field}: ${msg}` : msg;
      }).join('; ');
    }
  } catch { /* not JSON */ }
  return text || `Request failed (${status})`;
}

// Each portal keeps its own session, so a candidate and an HR account can be
// logged in side by side in the same browser without evicting each other.
export const roleForPath = (p = window.location.pathname) =>
  (p === '/admin' || p.startsWith('/admin/')) ? 'admin' : (p === '/hr' || p.startsWith('/hr/')) ? 'hr' : 'candidate';
const sessionKey = (role) => `hirelune_session_${role}`;
const readSession = (role) => { try { return JSON.parse(localStorage.getItem(sessionKey(role)) || 'null'); } catch { return null; } };

// One-time upgrade from the old single-session keys, so existing logins survive.
try {
  const t = localStorage.getItem('hirelune_token'); const r = localStorage.getItem('hirelune_role');
  if (t && r && !localStorage.getItem(sessionKey(r))) {
    localStorage.setItem(sessionKey(r), JSON.stringify({ ...JSON.parse(localStorage.getItem('hirelune_user') || '{}'), token: t, role: r }));
  }
  ['hirelune_token', 'hirelune_role', 'hirelune_user'].forEach((k) => localStorage.removeItem(k));
} catch { /* storage unavailable */ }

export const session = {
  token: (role) => readSession(role ?? roleForPath())?.token || null,
  role: () => roleForPath(),
  user: (role) => readSession(role ?? roleForPath()) || {},
  save: (data) => {
    localStorage.setItem(sessionKey(data.role), JSON.stringify(data));
    if (data.theme) localStorage.setItem('hirelune_theme', data.theme);
  },
  clear: (role = roleForPath()) => {
    localStorage.removeItem(sessionKey(role));
    if (role === 'candidate') ['hirelune_application_id', 'hirelune_candidate_id'].forEach((k) => localStorage.removeItem(k));
  },
};

async function raw(path, options = {}) {
  const token = session.token();
  const headers = options.body instanceof FormData
    ? { ...(options.headers || {}) }
    : { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  } catch {
    const error = new Error("Can't reach the Hirelune server. Check that the backend is running and try again.");
    error.status = 0;
    throw error;
  }
  if (!res.ok) {
    const text = await res.text();
    const error = new Error(res.status >= 500 && !text.startsWith('{') ? 'Something went wrong on the server. Please try again.' : errorMessage(res.status, text));
    error.status = res.status;
    if (res.status === 401 && token && !path.startsWith('/auth/')) {
      // Session expired server-side: drop it and tell the app shell.
      session.clear();
      window.dispatchEvent(new Event('hirelune:logout'));
    }
    throw error;
  }
  return res;
}

async function request(path, options = {}) {
  const res = await raw(path, options);
  return res.status === 204 ? null : res.json();
}

const json = (method, body) => ({ method, body: JSON.stringify(body ?? {}) });
const form = (fields) => {
  const fd = new FormData();
  Object.entries(fields).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') fd.append(k, v); });
  return { method: 'POST', body: fd };
};
const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.append(k, String(v)); });
  const s = p.toString();
  return s ? `?${s}` : '';
};

// Protected files (resumes, documents, offer PDFs, invoices) are fetched with the
// session header and opened as blob URLs — no tokens in URLs.
export async function openFile(path, { download = false, filename } = {}) {
  const res = await raw(path);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  if (download) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'download';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } else {
    window.open(url, '_blank', 'noopener');
  }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function fileObjectUrl(path) {
  const res = await raw(path);
  return URL.createObjectURL(await res.blob());
}

export const api = {
  // ---- auth
  candidateSignup: (data) => request('/auth/candidate/signup', json('POST', data)),
  candidateLogin: (data) => request('/auth/candidate/login', json('POST', data)),
  hrSignup: (data) => request('/auth/hr/signup', json('POST', data)),
  hrLogin: (data) => request('/auth/hr/login', json('POST', data)),
  adminLogin: (data) => request('/auth/admin/login', json('POST', data)),
  me: () => request('/auth/me'),
  logout: () => request('/auth/logout', { method: 'POST' }),
  changePassword: (data) => request('/auth/password', json('POST', data)),

  // ---- jobs
  getJobs: () => request('/jobs'),
  searchJobs: (params) => request(`/jobs/search${qs(params)}`),
  searchCandidates: (params) => request(`/candidates/search${qs(params)}`),
  getMyJobs: () => request('/jobs/mine'),
  getJob: (jobId) => request(`/jobs/${jobId}`),
  createJob: (data) => request('/jobs', json('POST', data)),
  setJobStatus: (jobId, status) => request(`/jobs/${jobId}/status`, json('PATCH', { status })),

  // ---- applications / candidates
  getCandidates: (jobId) => request(`/candidates${qs({ job_id: jobId })}`),
  getMyApplications: () => request('/me/applications'),
  getCandidate: (candidateId) => request(`/candidates/${candidateId}`),
  getCandidateScores: (candidateId) => request(`/candidates/${candidateId}/scores`),
  getCandidateAssessment: (candidateId) => request(`/candidates/${candidateId}/assessment`),
  unlockCandidate: (candidateId) => request(`/candidates/${candidateId}/unlock`, { method: 'POST' }),
  openResume: (candidateId, download = false) => openFile(`/candidates/${candidateId}/resume${download ? '?download=true' : ''}`, { download, filename: 'resume' }),
  createCandidate: (data) => request('/candidates', json('POST', data)),
  updateApplicationStatus: (applicationId, status, note) => request(`/candidates/applications/${applicationId}/status`, json('PATCH', { status, note: note || undefined })),
  uploadResume: (candidateId, file) => { const fd = new FormData(); fd.append('file', file); return request(`/resumes/${candidateId}`, { method: 'POST', body: fd }); },
  useProfileResume: (candidateId) => request(`/resumes/${candidateId}/from-profile`, { method: 'POST' }),

  // ---- assessments & coding
  startAssessment: (applicationId, options = {}) => request(`/assessments/start/${applicationId}${qs({ num_questions: options.numQuestions ?? 8, mcq_ratio: options.mcqRatio ?? 0.6 })}`, json('POST', { proctoring: options.proctoring })),
  proctorEvents: (applicationId, events, answers) => request(`/assessments/${applicationId}/proctor/events`, json('POST', { events, answers })),
  integrityReport: (applicationId) => request(`/assessments/${applicationId}/integrity`),
  applicationFeedback: (applicationId) => request(`/candidates/applications/${applicationId}/feedback`),
  getAssessmentStatus: (applicationId) => request(`/assessments/status/${applicationId}`),
  getAssessment: (applicationId) => request(`/assessments/${applicationId}`),
  saveAssessmentProgress: (applicationId, answers) => request(`/assessments/progress/${applicationId}`, json('PUT', { answers })),
  submitAssessment: (applicationId, answers) => request(`/assessments/submit/${applicationId}`, json('POST', { answers })),
  codingLanguages: () => request('/coding/languages'),
  runCode: (data) => request('/coding/run', json('POST', data)),
  submitCode: (data) => request('/coding/submit', json('POST', data)),
  codingProblems: () => request('/coding/problems'),
  generateAssessment: (data) => request('/hr/assessments/generate', json('POST', data)),
  assessmentTemplates: (jobId) => request(`/hr/assessments/templates${jobId ? `?job_id=${jobId}` : ''}`),
  assessmentTemplate: (id) => request(`/hr/assessments/templates/${id}`),
  updateAssessmentTemplate: (id, data) => request(`/hr/assessments/templates/${id}`, json('PUT', data)),
  publishAssessmentTemplate: (id) => request(`/hr/assessments/templates/${id}/publish`, { method: 'POST' }),
  unpublishAssessmentTemplate: (id) => request(`/hr/assessments/templates/${id}/unpublish`, { method: 'POST' }),
  deleteAssessmentTemplate: (id) => request(`/hr/assessments/templates/${id}`, { method: 'DELETE' }),
  createCodingProblem: (data) => request('/coding/problems', json('POST', data)),
  updateCodingProblem: (id, data) => request(`/coding/problems/${id}`, json('PUT', data)),
  verifyCodingProblem: (id, data) => request(`/coding/problems/${id}/verify`, json('POST', data)),

  // ---- interviews
  interviewOptions: () => request('/interviews/options'),
  getInterviews: (scope) => request(`/interviews${qs({ scope })}`),
  createInterview: (data) => request('/interviews', json('POST', data)),
  updateInterview: (id, data) => request(`/interviews/${id}`, json('PUT', data)),
  cancelInterview: (id, reason) => request(`/interviews/${id}${qs({ reason })}`, { method: 'DELETE' }),
  resendInterview: (id) => request(`/interviews/${id}/resend`, { method: 'POST' }),

  // ---- practice zone (mock interviews + mock assessments)
  practiceRoles: () => request('/practice/roles'),
  mockInterviews: () => request('/practice/interviews'),
  mockInterview: (id) => request(`/practice/interviews/${id}`),
  createMockInterview: (data) => request('/practice/interviews', json('POST', data)),
  mockInterviewBegin: (id) => request(`/practice/interviews/${id}/begin`, { method: 'POST' }),
  mockInterviewAnswer: (id, data) => request(`/practice/interviews/${id}/answer`, json('POST', data)),
  mockInterviewRunCode: (id, data) => request(`/practice/interviews/${id}/run-code`, json('POST', data)),
  mockInterviewFinish: (id) => request(`/practice/interviews/${id}/finish`, { method: 'POST' }),
  mockAssessments: () => request('/practice/assessments'),
  mockAssessment: (id) => request(`/practice/assessments/${id}`),
  createMockAssessment: (data) => request('/practice/assessments', json('POST', data)),
  saveMockAssessment: (id, data) => request(`/practice/assessments/${id}/progress`, json('PUT', data)),
  mockAssessmentRunCode: (id, data) => request(`/practice/assessments/${id}/run-code`, json('POST', data)),
  submitMockAssessment: (id, data) => request(`/practice/assessments/${id}/submit`, json('POST', data)),

  // ---- offers
  offerTemplates: () => request('/offers/templates'),
  createOfferTemplate: (data) => request('/offers/templates', json('POST', data)),
  updateOfferTemplate: (id, data) => request(`/offers/templates/${id}`, json('PUT', data)),
  deleteOfferTemplate: (id) => request(`/offers/templates/${id}`, { method: 'DELETE' }),
  offerDefaults: (applicationId) => request(`/offers/defaults/${applicationId}`),
  getOffers: () => request('/offers'),
  getOffer: (id) => request(`/offers/${id}`),
  createOffer: (data) => request('/offers', json('POST', data)),
  updateOffer: (id, data) => request(`/offers/${id}`, json('PUT', data)),
  reviseOffer: (id) => request(`/offers/${id}/revise`, { method: 'POST' }),
  sendOffer: (id) => request(`/offers/${id}/send`, { method: 'POST' }),
  deleteOffer: (id) => request(`/offers/${id}`, { method: 'DELETE' }),
  respondOffer: (id, decision, note) => request(`/offers/${id}/respond`, json('POST', { decision, note })),
  previewOfferPdf: (id) => openFile(`/offers/${id}/preview.pdf`),
  openOfferPdf: (id, download = false) => openFile(`/offers/${id}/pdf${download ? '?download=true' : ''}`, { download, filename: `Offer-${id}.pdf` }),

  // ---- profiles & verification
  getCandidateProfile: () => request('/candidate/profile'),
  updateCandidateProfile: (data) => request('/candidate/profile', json('PUT', data)),
  uploadCandidatePhoto: (file) => request('/candidate/profile/photo', form({ file })),
  uploadProfileResume: (file) => request('/candidate/profile/resume', form({ file })),
  openProfileResume: (download = false) => openFile(`/candidate/profile/resume${download ? '?download=true' : ''}`, { download, filename: 'resume' }),
  getHrProfile: () => request('/hr/profile'),
  updateHrProfile: (data) => request('/hr/profile', json('PUT', data)),
  uploadHrPhoto: (file) => request('/hr/profile/photo', form({ file })),
  uploadCompanyLogo: (file) => request('/hr/company/logo', form({ file })),
  uploadCompanyDocument: (docType, file) => request('/hr/company/documents', form({ doc_type: docType, file })),
  openCompanyDocument: (id) => openFile(`/hr/company/documents/${id}`),
  getVerification: () => request('/hr/verification'),
  submitVerification: () => request('/hr/verification', { method: 'POST' }),

  // ---- settings, notifications, email
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', json('PUT', data)),
  updateAccount: (data) => request('/settings/account', json('PUT', data)),
  getNotifications: (params) => request(`/notifications${qs(params)}`),
  unreadCount: () => request('/notifications/unread-count'),
  markNotificationRead: (id) => request(`/notifications/${id}/read`, { method: 'POST' }),
  markAllNotificationsRead: () => request('/notifications/read-all', { method: 'POST' }),
  smtpStatus: () => request('/email/status'),
  sendTestEmail: (to) => request('/email/test', json('POST', { to })),
  emailLogs: (params) => request(`/email/logs${qs(params)}`),
  retryEmail: (id) => request(`/email/logs/${id}/retry`, { method: 'POST' }),

  // ---- dashboards
  candidateDashboard: () => request('/dashboard/candidate'),
  hrDashboard: () => request('/dashboard/hr'),

  // ---- ATS, referrals, support
  atsCheck: (fields) => request('/ats/check', form(fields)),
  atsChecks: () => request('/ats/checks'),
  atsReport: (id) => request(`/ats/checks/${id}`),
  referrals: () => request('/referrals'),
  createReferral: () => request('/referrals', { method: 'POST' }),
  supportCategories: () => request('/support/categories'),
  createTicket: (fields) => request('/support/tickets', form(fields)),
  getTickets: (status) => request(`/support/tickets${qs({ status })}`),
  getTicket: (id) => request(`/support/tickets/${id}`),
  replyTicket: (id, body) => request(`/support/tickets/${id}/messages`, json('POST', { body })),
  setTicketStatus: (id, status) => request(`/support/tickets/${id}/status`, json('PATCH', { status })),
  openTicketAttachment: (id) => openFile(`/support/tickets/${id}/attachment`),

  // ---- credits & billing
  pricing: () => request('/billing/pricing'),
  billingSummary: (month) => request(`/billing/summary${qs({ month })}`),
  billingUsage: (month) => request(`/billing/usage${qs({ month })}`),
  transactions: (params) => request(`/billing/transactions${qs(params)}`),
  billingProfile: () => request('/billing/profile'),
  updateBillingProfile: (data) => request('/billing/profile', json('PUT', data)),
  createOrder: (credits, acceptTerms) => request('/billing/orders', json('POST', { credits, accept_terms: acceptTerms })),
  verifyOrder: (id, data) => request(`/billing/orders/${id}/verify`, json('POST', data)),
  failOrder: (id, reason) => request(`/billing/orders/${id}/fail`, json('POST', { reason })),
  orders: () => request('/billing/orders'),
  downloadInvoice: (id, number) => openFile(`/billing/invoices/${id}`, { download: true, filename: `${number || 'invoice'}.pdf` }),

  // ---- admin
  adminOverview: () => request('/admin/overview'),
  adminVerifications: (status) => request(`/admin/verifications${qs({ status })}`),
  adminApprove: (companyId) => request(`/admin/verifications/${companyId}/approve`, { method: 'POST' }),
  adminReject: (companyId, reason) => request(`/admin/verifications/${companyId}/reject`, json('POST', { reason })),
  adminUsers: (role, q) => request(`/admin/users${qs({ role, q })}`),
  adminAdjustCredits: (data) => request('/admin/credits', json('POST', data)),
  adminJobs: () => request('/admin/jobs'),
  adminAssignJob: (jobId, hrAccountId) => request(`/admin/jobs/${jobId}/owner`, json('PATCH', { hr_account_id: hrAccountId })),
  adminRunScheduler: () => request('/admin/scheduler/run', { method: 'POST' }),

  getHealth: () => request('/health'),
};
