#!/bin/bash

usage()
{
  printf "Available keys:
      --gerrit-url URL          Gerrit url (my.gerrit.com)
      --gerrit-port PORT        Gerrit port (29418)
      --after|--since DATE      lower border of reviews date range
      --before|--until DATE     upper border of reviews date range
      --project name            project name in Gerrit
      --branch name             branch name in Gerrit

  ./userstat.bash --gerrit-user <user> --project project --after 2021-04-01\n"
}

which jq > /dev/null
if [ $? -ne 0 ]
then
  mkdir -p ~/bin
  wget https://github.com/stedolan/jq/releases/download/jq-1.6/jq-linux64 -O ~/bin/jq
  chmod 755 ~/bin/jq
fi
export PATH=~/bin:${PATH}

GERRIT_URL=my.gerrit.com
GERRIT_PORT=29418
GERRIT_USER=$USER

#START=2020-12-01
#FINISH=2020-12-31
FINISH=$(date +%F)
PROJ="project"

STARTQUERY="after:${START}"
FINISHQUERY="before:${FINISH}"
PROJQUERY="project:${PROJ}"

# Set values
while [ $# -gt 0 ]
do
  case $1 in
    --gerrit-url)
      shift
      GERRIT_URL="$1"
      shift
      ;;
    --gerrit-port)
      shift
      GERRIT_PORT="$1"
      shift
      ;;
    --gerrit-user)
      shift
      GERRIT_USER="$1"
      shift
      ;;
    --after|--since)
      shift
      STARTQUERY="after:$1"
      shift
      ;;
    --before|--until)
      shift
      FINISHQUERY="before:$1"
      shift
      ;;
    --project)
      shift
      PROJQUERY="project:$1"
      shift
      ;;
    --branch)
      shift
      BRQUERY="branch:$1"
      shift
      ;;
    *)
      echo "unknown option $1!"
	  usage
      exit 1
      ;;
  esac
done

if [ ! -f $HOME/.ssh/id_rsa ]
then
  printf "Can't find ssh key $HOME/.ssh/id_rsa.\nGenerate it using following command:\n    ssh-keygen -q -N '' -f $HOME/.ssh/id_rsa\nand add it in 'SSH Public Keys' tab in your profile in gerrit."
  exit 1
fi

ssh -p $GERRIT_PORT -l $GERRIT_USER $GERRIT_URL &> /dev/null
if [ $? -ne 127 ]
then
  printf "Can't connect to Gerrit: 'ssh -p $GERRIT_PORT -l $GERRIT_USER $GERRIT_URL' failed.\nCheck 'SSH Public Keys' tab in your profile in gerrit.\n"
  exit 1
fi

ssh -p $GERRIT_PORT -l $GERRIT_USER $GERRIT_URL gerrit ls-projects | grep -q "${PROJECT}" &> /dev/null
if [ $? -gt 0 ]
then
  printf "Can't find project $PROJECT in $GERRIT_URL.\n"
  exit 1
fi

CSVFILE=reviewers_$(echo "$STARTQUERY" | tr ':' '_').csv
printf "SEP=;\n" > $CSVFILE

LINE="Review;Added;Deleted;Owner;Created;Merged;Reviewer;Number;Last Date"
printf "${LINE}\n" >> $CSVFILE

FULLLIST=$(ssh -p $GERRIT_PORT -l $GERRIT_USER $GERRIT_URL gerrit query \
  --format=JSON \
  ${STARTQUERY} ${FINISHQUERY} ${PROJQUERY} $BRQUERY \
  --patch-sets \
  --comments \
  --all-approvals)
  
echo "${FULLLIST}"
REVIWERS=($(echo "${FULLLIST}" \
  | jq 'select(.type != "stats") 
    | .owner.username as $OWNER 
    | .comments[] 
    | select(.reviewer.username != $OWNER
      and (.reviewer.name | test("public"; "ig") | not)
      and (.reviewer.name | test("Gerrit Code Review"; "ig") | not)
      and (.reviewer.name | test("dongjinguang"; "ig") | not))
    | .reviewer.email' \
  | sed 's|^"||g;s|"$||g' \
  | sort -u \
  ))
REVIWES=($(echo "${FULLLIST}" \
  | jq 'select(.type != "stats")
    | .number' \
  | sed 's|^"||g;s|"$||g' \
  | sort -u \
  ))

for i in ${REVIWES[*]}
do
  REVIEW=$(echo "${FULLLIST}" \
    | jq 'select(.type != "stats")
      | select(.number == "'${i}'" or .number == '${i}')')
  REVIEADD=$(echo "${REVIEW}" \
    | jq '.patchSets | sort_by(.number) | .[-1].sizeInsertions' \
    | sed 's|^"||g;s|"$||g')
  REVIEDEL=$(echo "${REVIEW}" \
    | jq '.patchSets | sort_by(.number) | .[-1].sizeDeletions' \
    | sed 's|^"||g;s|"$||g')
  OWNER=$(echo "${REVIEW}" \
    | jq '.owner.email' \
    | sed 's|^"||g;s|"$||g')
  TIMECREATED=$(echo "${REVIEW}" \
    | jq '.createdOn')
  if [ -n "$TIMECREATED" ]
  then DATECREATED=$(TZ="Europe/Moscow" date -d @$TIMECREATED +%x)
  else DATECREATED=""
  fi
  TIMEMERGED=$(echo "${REVIEW}" \
    | jq '[.patchSets | sort_by(.number) | .[] | select(.approvals != null and .approvals[].type == "SUBM")] | .[-1]?.approvals[]? | select(.type == "SUBM") | .grantedOn // ""')
  if [ -n "$TIMEMERGED" ]
  then DATEMERGED=$(TZ="Europe/Moscow" date -d @$TIMEMERGED +%F)
  else DATEMERGED=""
  fi

  echo "=== ${i}: ${OWNER}: ${DATECREATED} -> ${DATEMERGED} ==="
  REVIWERSFOUND=false
  for r in ${REVIWERS[*]}
  do
    COMMENTSDATES=$(echo "${REVIEW}" \
      | jq '.owner.email as $OWNER
        | .comments
        | sort_by(.timestamp)
        | .[]
        | select(.reviewer.email != $OWNER and .reviewer.email == "'${r}'") 
        | .timestamp')
    LASTDATE=$(echo "${COMMENTSDATES}" \
      | tail -1)
    DATENUMS=$(echo "${COMMENTSDATES}" \
      | wc -l)
#    if [ ${DATENUMS} -gt 0 ]
    if [ -n "${LASTDATE}" ]
    then
      REVIWERSFOUND=true
      LASTDATE=$(date -d @${LASTDATE} +%F)
      echo "=    ${r}: ${LASTDATE} (${DATENUMS})    ="
      LINE="https://$GERRIT_URL/#/c/${i};${REVIEADD};${REVIEDEL};${OWNER};${DATECREATED};${DATEMERGED};${r};${DATENUMS};${LASTDATE}"
      printf "${LINE}\n" >> $CSVFILE
    fi
  done
  if ! ${REVIWERSFOUND}
  then
    LINE="https://$GERRIT_URL/#/c/${i};${REVIEADD};${REVIEDEL};${OWNER};${DATECREATED};${DATEMERGED};;;"
    printf "${LINE}\n" >> $CSVFILE
  fi
done

