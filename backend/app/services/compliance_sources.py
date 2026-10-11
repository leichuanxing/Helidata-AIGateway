import fnmatch,unicodedata
from time import monotonic
import regex
from app.core.exceptions import APIError
def normalized(text):return unicodedata.normalize('NFKC',text).casefold()
def expression(kind,pattern):
 if kind=='regex':return regex.compile(pattern,regex.IGNORECASE|regex.VERSION1)
 if kind=='wildcard':return regex.compile(fnmatch.translate('*'+normalized(pattern)+'*'),regex.VERSION1)
 return None
def validate_pattern(kind,pattern):
 try:expression(kind,pattern)
 except (regex.error,ValueError):raise APIError(400,'COMPLIANCE_PATTERN_INVALID','正则或通配符格式无效') from None
def word_matches(words,text):
 results=[];folded=normalized(text);deadline=monotonic()+.1
 for word in words:
  remain=deadline-monotonic()
  if remain<=0:raise APIError(503,'COMPLIANCE_MATCH_TIMEOUT','敏感词审核超时，请重试')
  try:
   hit=normalized(word['pattern']) in folded if word['kind']=='text' else bool(expression(word['kind'],word['pattern']).search(folded if word['kind']=='wildcard' else text,timeout=min(.02,remain)))
  except TimeoutError:raise APIError(503,'COMPLIANCE_MATCH_TIMEOUT','正则审核超时，请修改规则') from None
  if hit:results.append({'source':'word','id':word['id'],'kind':word['kind'],'risk':word['risk'],'text':word['pattern'],'similarity':1})
 return results


def sample_literal_matches(samples, text):
 # Each non-empty sample line is a literal baseline; semantic checks cover paraphrases.
 results=[];folded=normalized(text);deadline=monotonic()+.1
 for sample in samples:
  if monotonic()>deadline:raise APIError(503,'COMPLIANCE_MATCH_TIMEOUT','审核样本原文匹配超时，请重试')
  for line in sample['text'].splitlines():
   candidate=normalized(line.strip())
   if candidate and candidate in folded:
    results.append({'source':'sample','id':sample['id'],'risk':sample['risk'],
                    'text':sample['text'],'matched_text':line.strip(),
                    'similarity':1,'match_type':'literal'})
    break
 return results
