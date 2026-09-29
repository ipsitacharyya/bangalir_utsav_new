function doPost(e) {
  const data=JSON.parse(e.postData.contents);
  const sheet=SpreadsheetApp.openById('YOUR_SHEET_ID').getSheetByName('Requests');
  sheet.appendRow([new Date(),data.song_title||'',data.artist||'',data.youtube_url||'',data.location||'']);
  MailApp.sendEmail('datascientistipsitacharyya@gmail.com','New Bangalir Utsav song request','Song: '+(data.song_title||'')+'\nArtist: '+(data.artist||'')+'\nYouTube: '+(data.youtube_url||'')+'\nLocation: '+(data.location||''));
  return ContentService.createTextOutput(JSON.stringify({ok:true})).setMimeType(ContentService.MimeType.JSON);
}
