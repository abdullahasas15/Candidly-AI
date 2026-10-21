/**
 * Unified Authentication Token Helper for Candidly Frontend
 *
 * Resolves tokens with proper role priority:
 * 1. Active user object / token prop
 * 2. Role-specific localStorage token ('candidly-auth-token-recruiter' or 'candidly-auth-token-candidate')
 * 3. Generic localStorage fallback ('candidly-auth-token')
 */

export function getRecruiterToken(user = null) {
  if (user?.access_token && user?.role === 'recruiter') {
    return user.access_token;
  }
  if (typeof window === 'undefined') return '';
  return (
    user?.access_token ||
    localStorage.getItem('candidly-auth-token-recruiter') ||
    localStorage.getItem('candidly-auth-token') ||
    ''
  );
}

export function getCandidateToken(user = null) {
  if (user?.access_token && user?.role === 'candidate') {
    return user.access_token;
  }
  if (typeof window === 'undefined') return '';
  return (
    user?.access_token ||
    localStorage.getItem('candidly-auth-token-candidate') ||
    localStorage.getItem('candidly-auth-token') ||
    ''
  );
}

export function getAuthHeaders(token, contentType = 'application/json') {
  const headers = {};
  if (contentType) {
    headers['Content-Type'] = contentType;
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}
