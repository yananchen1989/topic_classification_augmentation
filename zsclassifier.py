base_nli ={
    'politics':['Politics','War', 'Election','Constitution','Democracy','Conflict','Military',\
                'Terrorism', 'Government', 'Ideology', 'fascism', 'Socialism', 'Totalitarian', 'Religion'],
    'law':      ['Law', 'Legitimacy','Court','Crime','Murder','Jurisdiction'],
    'science':  ['Science','Aerospace','Physics','Chemistry','Biology','Scientist','Astronomy','Universe','Big Bang'],
    'technology':['Technology','Biotech', 'IT','Computers','Internet','Algorithm','Space','Bitcoin','artificial Intelligence','Robot'],
    'health': ['Health','Healthcare','Medicine','Clinics','Vaccine','Wellness','Nutrition','Dental','HIV','Disease'],
    'business': ['Business','Finance','Oil price','Supply','Inflation','Dollars','Bank','Wall Street','Bitcoin',
                        'Federal Reserve','Accrual','Accountancy','Sluggishness','Consumerism','Trade','Quarterly earnings',\
                         'Deposit','Revenue','Stocks','Recapitalization','Marketing','Futures'],
    'sports': ['Sports','Athletics','Championships','Football','Olympic','Tournament','Chelsea','League','Golf',
                            'NFL','Super bowl','World Cup'],
    'entertainment':['Entertainment','Pop music','Film','Music','Reality show','Drama','Concert','Rock music','Opera'],
    'education': ['Education', 'Tertiary education', 'University','Curriculum','Lecture'],
    'arts': ['Arts','Music','Painting','Art galleries','Classical music','Art Works','Stitchery'],
    'estate': ['Estate','Estate tax','Real estate']
}

def map_expand_nli(base_nli, dsn):
    label_expands_mannual = {}

    if dsn == 'ag':
        label_expands_mannual['World'] = base_nli['politics'] + base_nli['law']
        label_expands_mannual['Business'] = base_nli['business']
        label_expands_mannual['Sports'] = base_nli['sports']
        label_expands_mannual['science and technology'] = base_nli['science'] + base_nli['technology']

    elif dsn == 'uci':
        label_expands_mannual['entertainment'] = base_nli['entertainment']
        label_expands_mannual['business'] = base_nli['business']
        label_expands_mannual['science and technology'] = base_nli['science'] + base_nli['technology']
        label_expands_mannual['health'] = base_nli['health']

    elif dsn == 'nyt':
        label_expands_mannual['education'] = base_nli['education']
        label_expands_mannual['arts'] = base_nli['arts']
        label_expands_mannual['politics'] = base_nli['politics']
        label_expands_mannual['sports'] = base_nli['sports']
        label_expands_mannual['estate'] = base_nli['estate']
        label_expands_mannual['science'] = base_nli['science'] 
        label_expands_mannual['technology'] = base_nli['technology']
        label_expands_mannual['business'] = base_nli['business']
        label_expands_mannual['health'] = base_nli['health']
    return label_expands_mannual


import pandas as pd
import time,argparse
import os,math
import numpy as np
import datasets,re,operator,joblib
from sklearn.feature_extraction.text import CountVectorizer
from nltk.corpus import stopwords
import nltk,gensim
import tensorflow as tf
from sklearn.metrics.pairwise import cosine_distances,cosine_similarity 
assert gensim.__version__ == '4.1.2'

parser = argparse.ArgumentParser()
parser.add_argument("--dsn", default="yahoo", type=str)
parser.add_argument("--topk", default=32, type=int)
parser.add_argument("--fbs", default=64, type=int)
parser.add_argument("--acc_topn", default=1, type=int)
parser.add_argument("--manauto", default="auto", type=str)
parser.add_argument("--mode", default="test", type=str)
parser.add_argument("--calculate", default="sum", type=str)
parser.add_argument("--embed_cut", default=0.15, type=float)
parser.add_argument("--upper", default=0.85, type=float)
parser.add_argument("--lower", default=0.15, type=float)

parser.add_argument("--w1", default=0.5, type=float)
parser.add_argument("--w2", default=0.5, type=float)

parser.add_argument("--gpu", default="7", type=str)
parser.add_argument("--embedm", default="google", choices=['cmlm-base','cmlm-large','dan','google',\
                     'glove840b','glove6b', 'glove27b', 'glove42b'], type=str)
parser.add_argument("--w2v_thres", default=0.1, type=float)
args = parser.parse_args()

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu

#from utils.flair_ners import *

gpus = tf.config.list_physical_devices('GPU')
if gpus:
  try:
    for gpu in gpus:
      tf.config.experimental.set_memory_growth(gpu, True)
      # tf.config.experimental.set_virtual_device_configuration(gpu, \
      #      [tf.config.experimental.VirtualDeviceConfiguration(memory_limit=1024)])
  except RuntimeError as e:
    print(e)

from utils.load_data import * 

if args.dsn == 'nyt':
    samplecnt = 256
else:
    samplecnt = 2048
ds = load_data(dataset=args.dsn, samplecnt= samplecnt)
labels_candidates = ds.df_train['label_name'].unique().tolist()
print(labels_candidates)


from utils.encoders import *

if args.mode == 'train':
    enc = encoder('dan','cpu')




from transformers import pipeline
from transformers import AutoModelForSequenceClassification, AutoTokenizer

nli_model_name = 'vicgalle/xlm-roberta-large-xnli-anli' #"facebook/bart-large-mnli"
model_nli = AutoModelForSequenceClassification.from_pretrained(nli_model_name, cache_dir='./cache', local_files_only=True)
tokenizer_nli = AutoTokenizer.from_pretrained(nli_model_name, cache_dir='./cache', local_files_only=True)
nli_nlp = pipeline("zero-shot-classification", model=model_nli, tokenizer=tokenizer_nli, device=len(gpus)-1)

from transformers import BertTokenizer, BertForNextSentencePrediction
import torch
device0 = torch.device("cuda:{}".format(0) if torch.cuda.is_available() else "cpu")
bert_tokenizer = BertTokenizer.from_pretrained('bert-base-uncased', cache_dir='./cache', local_files_only=True)
bert_nsp = BertForNextSentencePrediction.from_pretrained('bert-base-uncased', cache_dir='./cache', local_files_only=True)
bert_nsp.to(device0)

# nltk.download('stopwords')
# stopwords = stopwords.words('english')
stopwords = joblib.load("./utils/stopwords")


def get_embedding_score(gram, df, enc):
    dfs = df.loc[df['title_lower'].str.contains(gram)]
    titles_contain = dfs.sample(min(2048, dfs.shape[0]))['title'].tolist()
    embeds = enc.infer(titles_contain, batch_size=1024)
    embeds_grams = enc.infer([gram])
    simi = cosine_similarity(embeds, embeds_grams).mean()
    return simi



from nltk.corpus import wordnet as wn
def check_noun(word):
    nets = wn.synsets(word)
    for net in nets:
        if net.name().split('.')[1] == 'n':
            return True 
    return False

############ find support seeds
if args.embedm == 'google':
    model_w2v = gensim.models.KeyedVectors.load_word2vec_format('./resource/GoogleNews-vectors-negative300.bin',binary=True)
elif args.embedm == 'glove840b':
    model_w2v = gensim.models.KeyedVectors.load_word2vec_format('./resource/glove.840B.300d.word2vec.txt', binary=False)
elif args.embedm == 'glove6b':
    model_w2v = gensim.models.KeyedVectors.load_word2vec_format('./resource/glove.6B.300d.word2vec.txt', binary=False)
elif args.embedm == 'glove27b':
    model_w2v = gensim.models.KeyedVectors.load_word2vec_format('./resource/glove.twitter.27B.200d.word2vec.txt', binary=False)
elif args.embedm == 'glove42b':
    model_w2v = gensim.models.KeyedVectors.load_word2vec_format('./resource/glove.42B.300d.word2vec.txt', binary=False)

vocab_w2v = set(list(model_w2v.index_to_key))


if args.mode == 'train':
    df = get_cc_news(1)
    df = df.loc[~df['title'].isnull()]
    df['title_lower'] = df['title'].map(lambda x: x.lower())
    gram_diff = {l:{} for l in labels_candidates}
    gram_embed = {}
    for ix, row in df.sample(frac=1).reset_index().iterrows():
        #row = ds.df_train.sample(1)
        #content = row['content'].tolist()[0]
        #label_name = row['label_name'].tolist()[0]
        if not row['title']:
            continue
        try:
            content = row['title'].lower()
        except:
            continue

        if not content or len(content.split(' ')) <=5:
            continue
        if re.search('[a-zA-Z]', content) is None:
            continue

        vectorizer = CountVectorizer(analyzer='word', ngram_range=(1, 1), lowercase=False)
        vectorizer.fit([content])
        grams = [g for g in vectorizer.get_feature_names() \
                        if g not in stopwords \
                            and g not in [ll.lower() for ll in labels_candidates] \
                            and not g.isdigit() \
                            and re.search('[a-zA-Z]', g) is not None \
                            and check_noun(g)]
        if not grams:
            continue
        #ners = get_ners(row['title'])
        #ners_ = [ner.lower() for ner in ners if len(ner.split(' '))>=2 and len(ner.split(' '))<=3]

        #grams = grams + ners_
        #print(grams)
        
        result_ori = nli_nlp(content, labels_candidates, multi_label=True, hypothesis_template="This text is about {}.")
        result_ori.pop('sequence')
        df_ori = pd.DataFrame(result_ori)

        # tune
        if df_ori['scores'].max() < 0.8:
            continue

        embeds = enc.infer([content])
        embeds_grams = enc.infer(grams)
        simis = cosine_similarity(embeds, embeds_grams)[0]
        df_gram_simis = pd.DataFrame(zip(grams, list(simis)), columns=['gram','simi'])
        #df_gram_simis['simi'] = (df_gram_simis['simi'] - df_gram_simis['simi'].min()) / (df_gram_simis['simi'].max()-df_gram_simis['simi'].min())
        df_gram_simis.sort_values(by=['simi'], ascending=False, inplace=True)
        # print(ix)
        # print("======>", content)
        # print("====>", grams)
        
        content_ = [content.replace(gram, '') for gram in grams]

        if len(content_)<=1:
            continue

        result_ = nli_nlp(content_,  labels_candidates, multi_label=True, hypothesis_template="This text is about {}.")

        for g,r in zip(grams, result_):
            # embedding score
            if not gram_embed.get(g, None):
                embed_score = get_embedding_score(g, df, enc)
                gram_embed[g] = embed_score

            if gram_embed[g] < args.embed_cut:
                continue

            r.pop('sequence')
            df_ = pd.DataFrame(r)
            df_diff = pd.merge(df_ori, df_, on=['labels'], how='inner') 
            df_diff['score_diff'] = df_diff['scores_x'] - df_diff['scores_y']
            df_diff_sel = df_diff.loc[(df_diff['scores_x']>=args.upper) & (df_diff['scores_y']<=args.lower)]
            
            if df_diff_sel.shape[0] == 0:
                continue
            print(g)
            print(df_diff_sel)
            for _, row in df_diff_sel.iterrows():
                if not gram_diff[row['labels']].get(g, None):
                    gram_diff[row['labels']][g] = []
                gram_diff[row['labels']][g].append(row['score_diff'])
            print("embed score:", gram_embed[g])
        print()


        if ix % 1000 ==0 and ix > 0 :
            print(ix)
            label_expands = {}
            for l, gram_scores in gram_diff.items():
                gram_scores_mean = {g:round(np.array(scores).mean(),4) for g, scores in gram_scores.items() }
                gram_scores_mean_sort = sorted(gram_scores_mean.items(), key=operator.itemgetter(1), reverse=True) 
                print(l, '===>', gram_scores_mean_sort[:50])
                label_expands[l] = [ii[0] for ii in gram_scores_mean_sort[:20]]
            print('\n')

            # save to disk
            joblib.dump(gram_diff, 'gram_diff___{}'.format(args.dsn))
            joblib.dump(gram_embed, 'gram_embed___{}'.format(args.dsn))



# elif args.mode == 'test':
#     gram_diff = joblib.load("gram_diff___{}".format(args.dsn))
#     #gram_embed = joblib.load("gram_embed___{}".format(args.dsn))

#     for args.topk in [16, 32, 50, 64]:

#         label_expands_auto = {}
#         for l, gram_scores in gram_diff.items():
#             gram_scores_mean = {g:round(np.array(scores).sum(),4) for g, scores in gram_scores.items() }
#             gram_scores_mean_sort = sorted(gram_scores_mean.items(), key=operator.itemgetter(1), reverse=True) 

#             label_expands_auto[l] = [l.lower()]

#             for j in gram_scores_mean_sort:
#                 if j[0] not in vocab_w2v:
#                     #print(j[0])
#                     continue

#                 if ' and ' in l:
#                     w0 = l.split('and')[0].strip().lower()
#                     w1 = l.split('and')[1].strip().lower()
#                     simi = max(model_w2v.similarity(w0, j[0]), model_w2v.similarity(w1, j[0]) )
#                 else:
#                     simi = model_w2v.similarity(l.lower(), j[0])

#                 if simi >= args.w2v_thres:
#                     label_expands_auto[l].append(j[0])
#                 if len(label_expands_auto[l])-1 == args.topk:
#                     break 

#             print(l, len(label_expands_auto[l]), label_expands_auto[l][:50], '\n')

#         # assign
#         if args.manauto == 'man':
#             label_expands = map_expand_nli(base_nli, args.dsn)
#         elif args.manauto == 'auto':
#             label_expands = label_expands_auto

#         grams_candidates = []
#         for l, grams in label_expands.items():
#             grams_candidates.extend(grams)
#         grams_candidates = list(set(grams_candidates))

#         ######## evaluate ###########
#         assert set(labels_candidates) == set(label_expands.keys())

#         accs_noexpand = []
#         accs_expand = []
#         for ix, row in ds.df_train.reset_index().iterrows():
#             content = row['content']

#             nli_result = nli_nlp([content],  labels_candidates, multi_label=True, hypothesis_template="This text is about {}.")
#             pred_label =  nli_result['labels'][0]
#             if pred_label == row['label_name']:
#                 accs_noexpand.append(1)
#             else:
#                 accs_noexpand.append(0)

#             df_buff_ll = []
#             for j in range(0, len(grams_candidates), 64):
#                 grams_candidates_buff = grams_candidates[j:j+64]
#                 nli_result_buff = nli_nlp([content],  grams_candidates_buff, multi_label=True, hypothesis_template="This text is about {}.")
#                 nli_result_buff.pop('sequence')  
#                 df_buff = pd.DataFrame(nli_result_buff)     
#                 df_buff_ll.append(df_buff)     

#             df_gram_score = pd.concat(df_buff_ll)
#             assert df_gram_score.shape[0] == len(grams_candidates)

#             infos = []
#             for l in label_expands.keys():
#                 l_score = np.array(([df_gram_score.loc[df_gram_score['labels']==gram, 'scores'].tolist()[0] for gram in label_expands[l]]  )).mean()
#                 infos.append((l, l_score))

#             df_expand = pd.DataFrame(infos, columns=['label','score'])

#             pred_label = df_expand.sort_values(by=['score'], ascending=False).head(1)['label'].tolist()[0]

#             if pred_label == row['label_name']:
#                 accs_expand.append(1)
#             else:
#                 accs_expand.append(0)
#                 # print(row['label_name'])
#                 # print(content)
#                 # print(df_expand.sort_values(by=['score'], ascending=False))
#                 # print()

#             if ix % 1024 == 0 and ix > 0:
#                 print(ix, sum(accs_noexpand) / len(accs_noexpand), sum(accs_expand)/len(accs_expand))

#         print("final_summary==>", ' '.join(['{}:{}'.format(k, v) for k, v in vars(args).items()]),
#              sum(accs_noexpand) / len(accs_noexpand), sum(accs_expand)/len(accs_expand) )



elif args.mode == 'test':
    gram_diff = joblib.load("gram_diff___{}".format(args.dsn))
    #gram_embed = joblib.load("gram_embed___{}".format(args.dsn))

    #for args.topk in [16, 32, 50, 64]:

    label_expands_auto = {}
    for l, gram_scores in gram_diff.items():
        gram_scores_mean = {g:round(np.array(scores).sum(),4) for g, scores in gram_scores.items() }
        gram_scores_mean_sort = sorted(gram_scores_mean.items(), key=operator.itemgetter(1), reverse=True) 

        label_expands_auto[l] = []

        for j in gram_scores_mean_sort:
            if j[0] not in vocab_w2v:
                #print(j[0])
                continue

            if ' and ' in l:
                w0 = l.split('and')[0].strip().lower()
                w1 = l.split('and')[1].strip().lower()
                simi = max(model_w2v.similarity(w0, j[0]), model_w2v.similarity(w1, j[0]) )
            else:
                simi = model_w2v.similarity(l.lower(), j[0])

            if simi >= args.w2v_thres:
                label_expands_auto[l].append(j[0])
            if len(label_expands_auto[l])-1 == args.topk:
                break 

        print(l, len(label_expands_auto[l]), label_expands_auto[l][:50], '\n')

    # assign
    if args.manauto == 'man':
        label_expands = map_expand_nli(base_nli, args.dsn)
    elif args.manauto == 'auto':
        label_expands = label_expands_auto

    grams_candidates = []
    for l, grams in label_expands.items():
        grams_candidates.extend(grams)
    grams_candidates = list(set(grams_candidates))

    ######## evaluate ###########
    assert set(labels_candidates) == set(label_expands.keys())

    accs_noexpand = []
    accs_expand = []
    for ix, row in ds.df_train.reset_index().iterrows():
        torch.cuda.empty_cache()
        content = row['content']

        nli_result = nli_nlp([content],  labels_candidates, multi_label=True, hypothesis_template="This text is about {}.")
        pred_label =  nli_result['labels'][:args.acc_topn]
        if row['label_name'] in pred_label:
            accs_noexpand.append(1)
        else:
            accs_noexpand.append(0)

        df_buff_ll = []
        for j in range(0, len(grams_candidates), args.fbs):
            grams_candidates_buff = grams_candidates[j:j+args.fbs]
            nli_result_buff = nli_nlp([content],  grams_candidates_buff, multi_label=True, hypothesis_template="This text is about {}.")
            nli_result_buff.pop('sequence')  
            df_buff = pd.DataFrame(nli_result_buff)     
            df_buff_ll.append(df_buff)     

        df_gram_score = pd.concat(df_buff_ll)
        assert df_gram_score.shape[0] == len(grams_candidates)

        infos = []
        for l in label_expands.keys():
            l_score = np.array(([df_gram_score.loc[df_gram_score['labels']==gram, 'scores'].tolist()[0] for gram in label_expands[l]]  )).mean()
            infos.append((l, l_score))

        df_expand = pd.DataFrame(infos, columns=['label','score'])

        # merge
        nli_result.pop('sequence')
        df_noexpand = pd.DataFrame(nli_result)
        df_noexpand = df_noexpand.rename(columns={'labels': 'label', 'scores':'score'})
         
        # nsp
        infos = []
        for l, grams in label_expands.items():
            nsp_scores = []
            nsp_grams = [l] + grams
            for ng in nsp_grams:
                sent2 = "This text is about {}.".format(ng)
                nsp_prob12 = nsp_infer(content, sent2, bert_nsp, bert_tokenizer)
                nsp_prob21 = nsp_infer(sent2, content, bert_nsp, bert_tokenizer)
                nsp_prob = (nsp_prob12+nsp_prob21) / 2    
                nsp_scores.append(nsp_prob)     
            nsp_scores_mean = sum(nsp_scores) / len(nsp_scores)
            infos.append((l, nsp_scores_mean))
        df_nsp = pd.DataFrame(infos, columns=['label','score'])

        df_merge = pd.merge(df_noexpand, df_expand, on=['label'], how='inner')\
                        .rename(columns={'score_x': 'score_noexpand', 'score_y':'score_expand'}) 

        df_merge_fuse = pd.merge(df_merge, df_nsp, on=['label'], how='inner')\
                          .rename(columns={'score': 'score_nsp'})         

        df_merge_fuse['score_fuse'] = args.w1 * df_merge_fuse['score_noexpand'].map(lambda x: math.log(x)) \
                                    + args.w2 * df_merge_fuse['score_expand'].map(lambda x: math.log(x))  \
                                    + (1-args.w1-args.w2) * df_merge_fuse['score_nsp'].map(lambda x: math.log(x))

        pred_label = df_merge_fuse.sort_values(by=['score_fuse'], ascending=False).head(args.acc_topn)['label'].tolist()

        if row['label_name'] in pred_label:
            accs_expand.append(1)
        else:
            accs_expand.append(0)

        if ix % 64 == 0 and ix > 0:
            print(ix, sum(accs_noexpand) / len(accs_noexpand), sum(accs_expand)/len(accs_expand))

    print("final_summary==>", ' '.join(['{}:{}'.format(k, v) for k, v in vars(args).items()]),
         sum(accs_noexpand) / len(accs_noexpand), sum(accs_expand)/len(accs_expand) )