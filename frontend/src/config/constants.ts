export const API_CONFIG = {
  DEFAULT_URL: import.meta.env.DEV ? '/api' : import.meta.env.VITE_API_URL || '',
};
