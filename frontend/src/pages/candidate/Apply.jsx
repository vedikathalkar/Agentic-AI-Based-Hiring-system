import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { CircleCheck, TriangleAlert, LoaderCircle } from 'lucide-react';
import { api, session } from '../../api';
import { FileUploader, PageHeader } from '../../components/ui';
import { formatScore } from '../../utils/score';

function ScreeningResult({ result, onTakeAssessment, starting, startError, onViewApplications }) {
  const screening = result.screening_result;
  const failed = !screening || screening.status === 'failed';
  return (
    <div className="card" style={{ padding: 28 }} role="status" aria-live="polite">
      <p className="row" style={{ color: 'var(--ok)', fontWeight: 600, fontSize: 18 }}>
        <CircleCheck size={22} aria-hidden="true" /> {failed ? 'Resume submitted' : 'Application submitted'} ✓
      </p>
      <dl className="kv" style={{ marginTop: 18, fontSize: 15 }}>
        <dt>Resume</dt><dd className="tone-ok">✓ Uploaded ({result.file_name})</dd>
        <dt>Screening</dt>
        <dd className={failed ? 'tone-danger' : 'tone-ok'}>{failed ? 'Could not be completed' : '✓ Completed'}</dd>
        {!failed && (
          <>
            <dt>Skill Score</dt><dd><b>{formatScore(screening.skill_score)}</b></dd>
            <dt>Experience Score</dt><dd><b>{formatScore(screening.experience_score)}</b></dd>
          </>
        )}
      </dl>
      {failed && (
        <p className="alert alert-warn" style={{ marginTop: 16 }}>
          <TriangleAlert size={15} aria-hidden="true" style={{ verticalAlign: -2, marginRight: 6 }} />
          Screening could not be completed{screening?.error ? ` (${screening.error})` : ''}. You can still take the assessment.
        </p>
      )}
      {screening?.warning && <p className="small muted" style={{ marginTop: 10 }}>{screening.warning}</p>}
      <p className="small muted" style={{ marginTop: 16 }}>
        The assessment has not started. Take it now, or come back later from <b>My Applications</b>.
      </p>
      {startError && <p className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{startError}</p>}
      <div className="row" style={{ marginTop: 18 }}>
        <button className="btn btn-primary" onClick={onTakeAssessment} disabled={starting}>
          {starting ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> Preparing assessment…</> : 'Take Assessment'}
        </button>
        <button className="btn btn-secondary" onClick={onViewApplications}>My Applications</button>
      </div>
    </div>
  );
}

export default function Apply() {
  const navigate = useNavigate();
  const { jobId } = useParams();
  const user = session.user();
  const [job, setJob] = useState(null);
  const [jobError, setJobError] = useState(null);
  const [profile, setProfile] = useState(null);
  const [file, setFile] = useState(null);
  const [useProfileResume, setUseProfileResume] = useState(false);
  const [name, setName] = useState(user.name || '');
  const [email, setEmail] = useState(user.email || '');
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [created, setCreated] = useState(null); // reused if the upload needs a retry

  useEffect(() => { api.getJob(jobId).then(setJob).catch((e) => setJobError(e.message)); }, [jobId]);
  useEffect(() => {
    api.getCandidateProfile().then((p) => {
      setProfile(p);
      if (p.phone) setPhone((v) => v || p.phone);
      if (p.resume_file_name) setUseProfileResume(true);
    }).catch(() => setProfile(null));
  }, []);

  const hasResume = useProfileResume ? Boolean(profile?.resume_file_name) : Boolean(file);

  const submit = async () => {
    if (!name.trim() || !email.trim() || !hasResume) {
      setError('Please provide your name, email, and a resume.');
      return;
    }
    setSubmitting(true); setError(null);
    try {
      let application = created;
      if (!application) {
        application = await api.createCandidate({ name, email, phone, job_id: Number(jobId) });
        localStorage.setItem('hirelune_application_id', String(application.application_id));
        setCreated(application);
      }
      // Uploading parses + screens the resume. It never starts the assessment.
      const upload = useProfileResume
        ? await api.useProfileResume(application.candidate_id)
        : await api.uploadResume(application.candidate_id, file);
      setResult(upload);
    } catch (err) { setError(err.message); }
    finally { setSubmitting(false); }
  };

  // The assessment page runs the guide and the camera/microphone check, then starts it.
  const takeAssessment = () => {
    localStorage.setItem('hirelune_application_id', String(created.application_id));
    navigate(`/assessment?application=${created.application_id}`);
  };

  if (jobError) return <p className="alert alert-danger" role="alert">This job is not available: {jobError}</p>;

  return (
    <div>
      <PageHeader title="Application" subtitle={job ? `Applying for ${job.title}${job.company_name ? ` at ${job.company_name}` : ''}${job.location ? ` · ${job.location}` : ''}` : 'Loading role…'}
                  actions={<button className="btn btn-secondary" onClick={() => navigate('/jobs')}>Find more jobs</button>} />
      {result ? (
        <ScreeningResult result={result} onTakeAssessment={takeAssessment} onViewApplications={() => navigate('/applications')} />
      ) : (
        <div className="card" style={{ padding: 28 }}>
          <h3 style={{ marginBottom: 16 }}>1. Personal information</h3>
          <div className="form-grid" style={{ marginBottom: 18 }}>
            <div className="field"><label className="field-label" htmlFor="ap-name">Full name *</label><input id="ap-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="field"><label className="field-label" htmlFor="ap-email">Email address *</label><input id="ap-email" className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
            <div className="field"><label className="field-label" htmlFor="ap-phone">Phone number</label><input id="ap-phone" className="input" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+91 …" /></div>
          </div>
          <h3 style={{ marginBottom: 12 }}>2. Resume</h3>
          {profile?.resume_file_name && (
            <fieldset style={{ border: 0, padding: 0, margin: '0 0 12px' }}>
              <legend className="sr-only">Resume source</legend>
              <label className="row small" style={{ marginBottom: 6 }}><input type="radio" name="src" checked={useProfileResume} onChange={() => setUseProfileResume(true)} /> Use my profile resume (<b>{profile.resume_file_name}</b>)</label>
              <label className="row small"><input type="radio" name="src" checked={!useProfileResume} onChange={() => setUseProfileResume(false)} /> Upload a different resume</label>
            </fieldset>
          )}
          {!useProfileResume && (
            <FileUploader label="Drag and drop your resume, or click to browse" hint="PDF or DOCX · max 5 MB" accept=".pdf,.docx"
                          onFile={setFile} fileName={file?.name} id="apply-resume" />
          )}
          <p className="small muted" style={{ margin: '12px 0 20px' }}>Your resume is parsed and screened against this role's requirements. The assessment starts only when you choose to take it.</p>
          {error && <p className="alert alert-danger" role="alert" style={{ marginBottom: 16 }}>{error}</p>}
          <button className="btn btn-primary btn-block" disabled={!hasResume || submitting} onClick={submit}>
            {submitting ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> Uploading and screening your resume…</> : 'Submit application'}
          </button>
        </div>
      )}
    </div>
  );
}
