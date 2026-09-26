/* Optional: shared Going/Skip voting when the site runs on a static host such as GitHub Pages.
   Leave both values empty and the site works without voting.
   To switch voting on, create a free Supabase project, run hosting/supabase.sql in its SQL editor,
   and paste two values from Supabase -> Project Settings -> API below. The "anon public" key is
   meant to be public; database rules (in supabase.sql) decide what it may do. */
window.FFM_CONFIG = {
  supabaseUrl: "",        // e.g. "https://abcdefghijklmnop.supabase.co"
  supabaseAnonKey: "",    // the "publishable" key (sb_publishable_...) or the legacy "anon public" key
};
