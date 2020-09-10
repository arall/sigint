# export PYTHONPATH=/usr/local/lib/python3/dist-packages/:$PYTHONPATH
# kal -s GSM900
# python3 simple_IMSI-catcher.py --sniff
# grgsm_livemon_headless --args=hackrf -f 938.0M
#
#
# grgsm_livemon -p 35 -f 938.2M   works
# grgsm_livemon -p 35 -f 937.4M   fails
# grgsm_livemon -p 35 -f 937.6M   fails
# grgsm_livemon -p 35 -f 937.8M   fails
# grgsm_livemon -p 35 -f 938.0M   fails
# grgsm_livemon -p 35 -f 938.2M   works