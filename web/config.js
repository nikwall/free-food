/* Optional: shared Going/Skip voting when the site runs on a static host such as GitHub Pages.
   Leave both values empty and the site works without voting.
   To switch voting on, create a free Supabase project, run hosting/supabase.sql in its SQL editor,
   and paste two values from Supabase -> Project Settings -> API below. The "anon public" key is
   meant to be public; database rules (in supabase.sql) decide what it may do. */
window.FFM_CONFIG = {
  supabaseUrl: "https://rykkwkogdilnaifignvu.supabase.co",
  supabaseAnonKey: "sb_publishable_MdwZc5n_DPuv5scI_CIOWA_VBXDoCBM",   // publishable: safe to be public
  newsletterForwardAddress: "hungrynieman@gmail.com",   // optional: an inbox the scanner reads (inbox/README.txt); shown on the Suggest page
};
