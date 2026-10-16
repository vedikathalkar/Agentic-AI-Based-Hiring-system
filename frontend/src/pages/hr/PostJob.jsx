import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';

const WEIGHTS = [['weight_skill', 'Skill'], ['weight_experience', 'Experience'], ['weight_test', 'Assessment']];
const splitRequirements = (value) => String(value || '').split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
const isWholeNumber = (v) => v !== '' && Number.isInteger(Number(v)) && Number(v) >= 0;

export default function PostJob() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: '', team: '', location: '', requirements: '', preferred_skills: '', education_requirement: '', description: '',
    min_experience: 0, open_positions: 1,
    weight_skill: 40, weight_experience: 20, weight_test: 40,
    coding_questions: 0, assessment_minutes: 30,
  });
  const { me, toast } = useApp();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));
  const weightTotal = WEIGHTS.reduce((sum, [key]) => sum + (Number(form[key]) || 0), 0);
  const skills = splitRequirements(form.requirements);

  const problems = useMemo(() => {
    const p = {};
    if (!form.title.trim()) p.title = 'Role title is required.';
    if (!skills.length) p.requirements = 'Add at least one required skill.';
    if (form.min_experience === '' || Number(form.min_experience) < 0 || Number.isNaN(Number(form.min_experience))) p.min_experience = 'Minimum experience must be 0 or more.';
    if (WEIGHTS.some(([k]) => !isWholeNumber(form[k]))) p.weights = 'Each weight must be a whole number of 0 or more.';
    else if (weightTotal !== 100) p.weights = 'Weights must add up to exactly 100.';
    return p;
  }, [form, skills.length, weightTotal]);
  const valid = Object.keys(problems).length === 0;
  const show = (k) => touched && problems[k];

  const publish = async () => {
    setTouched(true);
    if (!valid) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.createJob({
        ...form,
        title: form.title.trim(),
        min_experience: Number(form.min_experience),
        open_positions: Number(form.open_positions) || 1,
        weight_skill: Number(form.weight_skill),
        weight_experience: Number(form.weight_experience),
        weight_test: Number(form.weight_test),
        coding_questions: Number(form.coding_questions),
        assessment_minutes: Number(form.assessment_minutes),
      });
      toast('Role published', 'ok');
      navigate('/hr/jobs');
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
        <p className="eyebrow">New role</p>
        <h1 style={{ marginTop: 8, marginBottom: 24 }}>Post a job requirement</h1>
        {me && me.verification_status !== 'verified' && (
          <p className="alert alert-warn" role="alert">Only verified companies can publish roles. <Link to="/hr/verification">Complete verification</Link> first.</p>
        )}

        <form className="card" style={{ padding: 28 }} onSubmit={(e) => { e.preventDefault(); publish(); }} noValidate>
          <div style={{ marginBottom: 18 }}>
            <label className="field-label" htmlFor="job-title">Role title *</label>
            <input id="job-title" className="input" placeholder="e.g. ML Engineer, Associate" value={form.title} onChange={set('title')} aria-invalid={!!show('title')} />
            {show('title') && <p className="small tone-danger" style={{ marginTop: 4 }}>{problems.title}</p>}
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18, gap: 16 }}>
            <div>
              <label className="field-label" htmlFor="job-team">Team</label>
              <input id="job-team" className="input" placeholder="e.g. Platform" value={form.team} onChange={set('team')} />
            </div>
            <div>
              <label className="field-label" htmlFor="job-location">Location</label>
              <input id="job-location" className="input" placeholder="e.g. Mumbai · Hybrid" value={form.location} onChange={set('location')} />
            </div>
          </div>

          <div style={{ marginBottom: 18 }}>
            <label className="field-label" htmlFor="job-reqs">Required skills *</label>
            <textarea id="job-reqs" className="input" rows={3} placeholder="Skills can be separated by commas, semicolons or new lines." value={form.requirements} onChange={set('requirements')} aria-invalid={!!show('requirements')} aria-describedby="job-reqs-help" />
            <p id="job-reqs-help" className="small muted" style={{ marginTop: 4 }}>
              {skills.length ? `${skills.length} skill${skills.length === 1 ? '' : 's'}: ${skills.join(' · ')}` : 'These exact skills are used to calculate each candidate’s skill score.'}
            </p>
            {show('requirements') && <p className="small tone-danger">{problems.requirements}</p>}
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18, gap: 16 }}>
            <div>
              <label className="field-label" htmlFor="job-pref">Preferred skills</label>
              <input id="job-pref" className="input" placeholder="Nice to have, e.g. Docker, AWS" value={form.preferred_skills} onChange={set('preferred_skills')} />
              <p className="small muted" style={{ marginTop: 4 }}>Shown in ATS reports; not required to apply.</p>
            </div>
            <div>
              <label className="field-label" htmlFor="job-edu">Education requirement</label>
              <input id="job-edu" className="input" placeholder="e.g. B.Tech / B.E. in Computer Science" value={form.education_requirement} onChange={set('education_requirement')} />
              <p className="small muted" style={{ marginTop: 4 }}>Informational only — never used in ranking.</p>
            </div>
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18, gap: 16 }}>
            <div>
              <label className="field-label" htmlFor="job-minexp">Minimum experience (years)</label>
              <input id="job-minexp" className="input" type="number" min={0} step="0.5" value={form.min_experience} onChange={set('min_experience')} aria-invalid={!!show('min_experience')} />
              {show('min_experience') && <p className="small tone-danger" style={{ marginTop: 4 }}>{problems.min_experience}</p>}
            </div>
            <div>
              <label className="field-label" htmlFor="job-open">Open positions</label>
              <input id="job-open" className="input" type="number" min={1} value={form.open_positions} onChange={set('open_positions')} />
            </div>
          </div>

          <div className="grid grid-2" style={{ marginBottom: 18, gap: 16 }}>
            <div>
              <label className="field-label" htmlFor="job-coding">Coding questions in the assessment</label>
              <select id="job-coding" className="input" value={form.coding_questions} onChange={set('coding_questions')}>
                {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n === 0 ? 'None' : n}</option>)}
              </select>
              <p className="small muted" style={{ marginTop: 4 }}>Chosen from the problem bank by matching your required skills.</p>
            </div>
            <div>
              <label className="field-label" htmlFor="job-min">Assessment time limit (minutes)</label>
              <input id="job-min" className="input" type="number" min={5} max={180} value={form.assessment_minutes} onChange={set('assessment_minutes')} />
            </div>
          </div>

          <div style={{ marginBottom: 18 }}>
            <label className="field-label" htmlFor="job-desc">Role description</label>
            <textarea id="job-desc" className="input" rows={5} placeholder="What this person will own, and what success looks like in the first 6 months." value={form.description} onChange={set('description')} />
          </div>

          <fieldset style={{ border: 0, padding: 0, margin: '0 0 22px' }}>
            <legend className="field-label">Scoring weights (must total 100)</legend>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12 }}>
              {WEIGHTS.map(([key, label]) => (
                <div key={key}>
                  <label className="small muted" htmlFor={key}>{label} %</label>
                  <input id={key} className="input" type="number" min={0} max={100} step={1} value={form[key]} onChange={set(key)} aria-invalid={!!problems.weights} />
                </div>
              ))}
            </div>
            <p role="status" aria-live="polite" className={`small ${weightTotal === 100 && !problems.weights ? 'tone-ok' : 'tone-danger'}`} style={{ marginTop: 8, fontWeight: 600 }}>
              Weight total: {weightTotal}%{problems.weights ? ` — ${problems.weights}` : ' ✓'}
            </p>
            <p className="small muted">Education is not part of scoring.</p>
          </fieldset>

          {error && <p className="alert alert-danger" role="alert" style={{ marginBottom: 16 }}>Couldn't publish: {error}</p>}

          <div className="row">
            <button type="submit" className="btn btn-primary" disabled={submitting || !!problems.weights}>
              {submitting ? 'Publishing…' : 'Publish role'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => navigate('/hr/jobs')}>Cancel</button>
          </div>
        </form>
    </div>
  );
}
