import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Logo from '../../components/Logo';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';

export default function AdminLogin() {
  const { login } = useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setError(''); setLoading(true);
    try { login(await api.adminLogin({ username, password })); navigate(location.state?.from || '/admin', { replace: true }); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  };
  return (
    <div style={{ minHeight: '100vh', background: 'var(--side)', display: 'grid', placeItems: 'center', padding: 24 }}>
      <form className="card" style={{ width: '100%', maxWidth: 400, padding: 32 }} onSubmit={submit}>
        <Link to="/" style={{ display: 'inline-flex', marginBottom: 18 }}><Logo size={28} /></Link>
        <p className="eyebrow">Admin console</p>
        <h1 style={{ fontSize: 26, margin: '6px 0 20px' }}>Sign in</h1>
        <div className="field"><label className="field-label" htmlFor="ad-u">Username</label><input id="ad-u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></div>
        <div className="field"><label className="field-label" htmlFor="ad-p">Password</label><input id="ad-p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
        {error && <p className="alert alert-danger small" role="alert">{error}</p>}
        <button className="btn btn-primary btn-block" style={{ marginTop: 8 }} disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  );
}
