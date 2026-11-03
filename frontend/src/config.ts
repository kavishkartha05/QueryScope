// Site-level settings that are not secrets.

// Where "request access" emails go. Public: it ships in the bundle.
export const CONTACT_EMAIL = "kavish01+queryscope@gmail.com";

export const GITHUB_URL = "https://github.com/kavishkartha05/QueryScope";

export const REQUEST_ACCESS_HREF =
  "mailto:" + CONTACT_EMAIL + "?subject=" + encodeURIComponent("QueryScope demo access request");
