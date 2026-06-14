# AI_USAGE.md - AI Usage Log and Corrections

This document tracks the usage of AI tools during the development of the SplitAudit application.

---

## 1. AI Tools & Prompts Used

* **AI System**: Gemini 3.5 Flash (High) (acting as coding assistant), ChatGPT(for planning initial steps and tech stack)
* **Key Prompts**:
  * "Create the initial implementation plan for a production-quality expense sharing Django application"
  * "The approve button should be removed(it was appearing after every record), a record can either be rejected or edited and the engine will approved it automatically based on policies"
  * "Improved the visuals and UI add in charts and bar graphs for exact share the current user has in expenses and a graph showing everyone's proportion in total expenses, add a sidebar for navigation, and create a GitHub styled UI"

---

## 2. AI Correction Log (3 Cases)

### Case 1: Fetching all the expenses records at once and displaying them

* **What the AI did**:
  Fetched all the records from the DB and displayed them all at once on the expenses info page.
* **Why it was Wrong**:
  Not only is that not optimal, a record containing hundreds of expenses could easily extend the current page 10 times the width of the normal page.
* **How it was Corrected**:
  We used pagination to handle this, with a record limit of 15.

---

### Case 2: Treating records with unregistered users as an anomaly and asking users to edit the cell

* **What the AI Suggested**:
  It treated any names say 'dev' and 'dev's friend "X"' as a potential anomaly and then asked users to reject or edit the cell
* **Why it was Wrong**:
  The admin can ofcourse reject it so there should be another option rather just rejecting it or creating a new user and repeat the whole process, it could be a partial member and not even permanent in the group.
* **How it was Corrected**:
  So instead of manually creating a user and running the engine again the engine does it for you. It creates a user with the missing person's name and the credentials for the same are visible on top of the report, alternatively admin can also reject the record.

  
### Case 3: Approving every row instead of utilising policies

* **What the AI Suggested**:
  It suggested to have an approved button in front of every record, so that user can approve it manually
* **Why it was Wrong**:
  Policies exist for this exact same purpose if we have to approve every single record, what good will it be. Although the policies existed but approval was still required.
* **How it was Corrected**:
  Instead of approving every single records, we added custom options for some specific cases, for example duplicate entries can be auto-approved but if the user wants to keep this record, there should be an option for the same. 
