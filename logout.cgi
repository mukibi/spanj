#!/usr/bin/perl
use strict;
use warnings;

use CGI;
use Fcntl qw/:flock SEEK_END/;	
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $cont="/";
my $id;

if (exists $ENV{"QUERY_STRING"} and $ENV{"QUERY_STRING"} =~ /^.*&?cont=(.+)&?$/i) {
        $cont = $1;
}


if ( exists $ENV{"HTTP_SESSION"} ) {
	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
        my @tuple;
        for my $unprocd_tuple (@session_data) {
                @tuple = split/=/,$unprocd_tuple;
                if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
                        $session{$tuple[0]} = $tuple[1];
                }
        }
	$id = $session{"id"};
	$session{"id"} = "";
	$session{"name"} = "";
	$session{"privileges"} = "";
	$session{"tries"} = 0; 
	$session{"token_expiry"} = "";
	$session{"sess_key"} = "";
	$session{"profile"} = "";

$session{"stage"} = "";
#analysis
$session{"classes"} = "";
$session{"exams"} = "";
$session{"subjects"} = "";
$session{"clubs_societies"} = "";
$session{"responsibilities"} = "";
$session{"sports_games"} = "";
$session{"dorms"} = "";
$session{"marks_at_adm"} = "";
$session{"analysis_type"} = "";
$session{"analysis_id"} = "";
$session{"confirm_code"} = "";
$session{"ta_sort_by"} = "";
$session{"ta_sort_order"} = "";
$session{"search"} = "";
$session{"recover_uid"} = "";
$session{"recover_code"} = "";
#messenger
$session{"job_name"} = "";
$session{"modem"} = "";
$session{"modem_path"} = "";
$session{"datasets"} = "";
$session{"message_template"} = "";
$session{"message_validity"} = "";
$session{"db_filter_type"} = "";
$session{"db_filter"} = "";


}

my @today = localtime;
my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");

if ($log_f) {
	@today = localtime;
        my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
	flock ($log_f, LOCK_EX);
	seek($log_f, 0, SEEK_END);
        print $log_f "$id LOGOUT $time\n";
	flock($log_f, LOCK_UN);
        close $log_f;
}
else {
	print STDERR "Could not open log file: $!\n";
}
	
my @new_sess_array;

for my $sess_key (keys %session) {
     	push @new_sess_array, $sess_key."=".$session{$sess_key};
}

my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session:  $new_sess\r\n";
print "Status: 302 Moved Temporarily\r\n";
print "Location: $cont\r\n";

my $clean_url = htmlspecialchars($cont);        
my $res = 
         "<html>
         <head><title>Spanj: Exam Management Information System - Redirect Failed</title></head>
         <body>
         You should have been redirected to <a href=\"$clean_url\">$clean_url</a>. If you were not, <a href=\"$clean_url\">Click Here</a> 
         </body>
         </html>";
my $content_len = length($res); 
print "Content-Length: $content_len\r\n";
print "\r\n";
print $res;

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

