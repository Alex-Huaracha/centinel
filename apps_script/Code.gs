// Lets Centinel read the user's Gmail. It only reads: appsscript.json grants
// the gmail.readonly scope, so this script can never send, change or delete mail.
//
// Every request must carry the secret stored in the script property
// CENTINEL_SECRET. Errors are returned as {"error": "..."} because a web app
// cannot set HTTP status codes.

function doGet(e) {
  const params = e.parameter;
  const secret =
    PropertiesService.getScriptProperties().getProperty("CENTINEL_SECRET");
  if (!secret || params.secret !== secret) {
    return json_({ error: "unauthorized" });
  }
  if (params.action === "search") {
    return json_(search_(params.senders.split(","), Number(params.days)));
  }
  if (params.action === "get") {
    return json_(get_(params.id));
  }
  return json_({ error: "unknown action" });
}

// Emails from any of the senders received in the last `days` days.
function search_(senders, days) {
  const query = `from:(${senders.join(" OR ")}) newer_than:${days}d`;
  const emails = [];
  let pageToken;
  do {
    const page = Gmail.Users.Messages.list("me", { q: query, pageToken });
    for (const { id } of page.messages || []) {
      const message = Gmail.Users.Messages.get("me", id, {
        format: "metadata",
        metadataHeaders: ["From"],
      });
      emails.push({
        id,
        from: message.payload.headers[0].value,
        received_at_ms: Number(message.internalDate),
      });
    }
    pageToken = page.nextPageToken;
  } while (pageToken);
  return { emails };
}

// The whole email as it arrived (RFC 822), base64-encoded.
function get_(id) {
  let message;
  try {
    message = Gmail.Users.Messages.get("me", id, { format: "raw" });
  } catch (error) {
    // Gmail says "Requested entity was not found." for a deleted email.
    if (String(error).toLowerCase().includes("not found")) {
      return { error: "not found" };
    }
    throw error;
  }
  // Depending on the runtime, raw comes as bytes or as a base64url string.
  const bytes =
    typeof message.raw === "string"
      ? Utilities.base64DecodeWebSafe(message.raw)
      : message.raw;
  return { id, raw: Utilities.base64Encode(bytes) };
}

function json_(body) {
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(
    ContentService.MimeType.JSON
  );
}
