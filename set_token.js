window.localStorage.setItem('finance-llm-token', 'eyJzaWQiOiIyYWJhNzE2MzAyNDA1MDVmNjNjYWY5ZDEwODBiY2Y2ZjdiYzY3MTQ5NDg0MGQ4ZGMiLCJzdWIiOiJiMTE2MTMyNDA4N2I4NjY1N2FkYWI3ZDdjYmI2YzVjMSIsImlhdCI6MTc5MzgwNDU5MiwiZXhwIjoxNzk2Mzk2NTkyfQ.WkEqTVfOUtKqULrgFqSsAyPzx7UJVQJwMinG9X63Ka4');
if (navigator.serviceWorker) { navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())); }
window.location.href = '/execucoes';
