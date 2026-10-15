from api import reports_studio as studio
res = studio.attach_pdf("rep-8f73c00d32", "sistema (revisão de layout)", {"user_id": "u-admin", "email": "teste@teste.com", "see_all": True})
print("novo pdf:", res["file"]["id"], res["file"]["name"], res["file"]["size"], "| ficheiros:", len(res["report"]["files"]))
