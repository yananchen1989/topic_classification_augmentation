from load_data import * 
from transblock import * 
from transformers import pipeline
#nlp = pipeline("zero-shot-classification", model="joeddav/bart-large-mnli-yahoo-answers", device=0) #  

'''
from transformers import AutoModelForSequenceClassification, AutoTokenizer
#https://huggingface.co/joeddav/bart-large-mnli-yahoo-answers
MODEL = "joeddav/bart-large-mnli-yahoo-answers"
#'facebook/bart-large-mnli'  'joeddav/xlm-roberta-large-xnli'
from transformers import BartForSequenceClassification, BartTokenizer
tokenizer = BartTokenizer.from_pretrained(MODEL)
nli_model = BartForSequenceClassification.from_pretrained(MODEL)
import torch
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
nli_model.to(device)


infos = []
ix = 0
while ix < len(sentences):
    premises = sentences[ix:ix+batch_size]

    for cate in labels:
        hypothesises = ['This text is about {}.'.format(cate)] * batch_size
        # run through model pre-trained on MNLI
        x = tokenizer(premises, hypothesises, return_tensors='pt', padding=True ,truncation=True,max_length=64)

        logits = nli_model(**x.to(device))[0] 
        entail_contradiction_logits = logits[:,[0,2]].softmax(dim=1)
        true_prob = entail_contradiction_logits[:,1].cpu().detach().numpy()
        
        if true_prob.max() >= 0.9: 
            pos = np.where(true_prob>=0.9)[0]
            for p in pos:
                #print(premises[p])
                infos.append((premises[p], cate))
    ix += batch_size
    logger.info('ix==>{}'.format(ix))

    gc.collect()

'''


model = "facebook/bart-large-mnli"
nlp = pipeline("zero-shot-classification", model=model, device=0) # 
print(model, ' loaded')
for dsn in ['ag','pop','uci','bbc','bbcsport','tweet']:
    ds = load_data(dataset=dsn)
    labels_candidate = list(ds.df['label'].unique())
    print(dsn, ' ==>', labels_candidate)
    #dfi = ds.df.sample(min(ds.df.shape[0], sample_cnt))
    correct = 0
    for ix, row in ds.df.iterrows():
        label = row['label']
        content = row['content']
        content_ = ' '.join(content.split(' ')[:50])
        result = nlp(content_, labels_candidate, multi_label=False, hypothesis_template="This text is about {}.")
        pred = result['labels']
        if pred[0] == label:
            correct += 1
    print(dsn, ' acc==>',  correct / ds.df.shape[0])





for dsn in ['yahoo']:
    ds = load_data(dataset=dsn)
    labels_candidate = list(ds.df_test['label'].unique())
    print(dsn, ' ==>', labels_candidate)
    correct = 0
    for ix, row in ds.df_test.iterrows():
        label = row['label']
        content = row['content']
        #content_ = ' '.join(content.split(' ')[:50])
        result = nlp(content, labels_candidate, multi_label=False, hypothesis_template="This text is about {}.")
        pred = result['labels']
        if pred[0] == label:
            correct += 1
    if ix % 1000:
        print('step acc==>', correct / ix)
    print(dsn, ' acc==>',  correct / ds.df_test.shape[0])






model = "roberta-large-mnli"
nlp = pipeline("zero-shot-classification", model=model, device=0) # 
print(model, ' loaded')
for dsn in ['yahoo']:
    ds = load_data(dataset=dsn)
    labels_candidate = list(ds.df_test['label'].unique())
    print(dsn, ' ==>', labels_candidate)
    #dfi = ds.df.sample(min(ds.df.shape[0], sample_cnt))
    correct = 0
    for ix, row in ds.df_test.iterrows():
        label = row['label']
        content = row['content']
        #content_ = ' '.join(content.split(' ')[:50])
        result = nlp(content, labels_candidate, multi_label=False, hypothesis_template="This text is about {}.")
        pred = result['labels']
        if pred[0] == label:
            correct += 1
    if ix % 1000:
        print('step acc==>', correct / ix)
    print(dsn, ' acc==>',  correct / ds.df_test.shape[0])












