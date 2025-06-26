gerrit_review_tracking.exe -d 2019-06

Run the cmd command to obtain the submission of the Gerrit repository of the group members.
Create an Excel file for the team members in the same directory and fill in the accessory file config.ini.

config.ini:
gerrit-url: indicates the repository for collecting code. Multiple repository can be obtained at the same time. Use ". (;) to separate
username and password: account and password for accessing Gerrit. Ensure that you have the permission to access all specified repositories.
member-list: indicates the member list. The member list is in the format of Name and Email. You can refer to the file in the original directory.

The mandatory parameter is the start date to be matched. The original date string format is 2019-06-20 02:07:27.000000000.
Regular expressions can be used, for example:
2019: Collect submissions in 2019
2019-06: Collect submissions made in June 2019.
2019-06-2[2-5]: Collect submissions from June 22 to 25, 2019.
2019-06-24: Collect submissions on June 24, 2019.


Gitlab
To allow python work with server's certificates which do not exist in "certifi" package it is required to crete bundle-ca file:
1. Export CA from "Trusted Root Certification Authorities" and "Intermediate Certification Authorities" in Base64 format:
	a. IT Root CA
	b. Enterprise CA 1
	Note that certificate and certification path can be different for different sites, thus check with particular site
2. Create a new file "bandle-ca" and put there content of exported certificates in reverse order:
	a. Intermediate certificates
	b. Root CA
Another option is to export certificate chain directly in Base64 format and copy-paste content into bundle-ca file

Codehub
API description:
N/A

Sharepoint:
API description:
 - https://docs.microsoft.com/en-us/previous-versions/office/developer/sharepoint-rest-reference/jj860569(v=office.15)
 - generate token by `echo -n 'user:password' | base64`
 - run as Sharepoint_statistics.py -d 2022-01-01
 - this will show all documents updated after 2022-01-01 (including this date)